import os
import json
import docker
import tempfile
import google.generativeai as genai

print("Configuring Gemini API client for Programming Analysis...")
try:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    programming_model = genai.GenerativeModel('gemini-1.5-pro')
    print("Gemini model for programming analysis configured successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to configure Gemini model: {e}")
    programming_model = None


def analyze_programming_submission(question: str, ocr_code: str) -> dict:
    """
    Analyzes a programming submission with multiple sub-questions.
    - Splits the question into parts.
    - Splits the OCR code into individual programs.
    - Sequentially assigns programs to parts.
    - If program needs input -> run in Docker, else Gemini-only.
    - Generates a final summary remark.
    """
    if not programming_model or not ocr_code:
        return {'score': 0.0, 'justification': 'Missing model or student code.'}

    # --- Step 1: Split question into sub-parts ---
    parts = _split_question_into_parts(question)
    if not parts:
        parts = [question]

    # --- Step 2: Split OCR text into programs ---
    programs = _split_programs(ocr_code)
    if not programs:
        return {'score': 0.0, 'justification': 'No valid programs were found in the submission.'}

    total_score = 0.0
    all_justifications = []
    mapped_count = min(len(programs), len(parts))

    # --- Step 3: Map programs sequentially to parts ---
    for i in range(mapped_count):
        program_code = programs[i]
        part_question = parts[i]

        print(f"--- Analyzing Program {i+1}/{mapped_count} for Part: {part_question[:50]}...")

        try:
            language = _detect_language(program_code)
            if language == "unsupported":
                all_justifications.append(f"P{i+1}: Could not detect a supported language, skipped.")
                continue

            fixed_code = _fix_code(program_code, language)
            score = 0.0 # Default score

            if _requires_input(fixed_code):
                # Run with Docker + Test Cases
                test_cases = _generate_test_cases(part_question, language)
                if not test_cases:
                    all_justifications.append(f"P{i+1}: Could not generate test cases.")
                    continue
                
                # First, verify if the code solves the intended problem
                problem_check_prompt = f"""
                Compare if this code solves the following question AS WRITTEN (do not add additional requirements):
                Original Question: {part_question}
                Student's Code:
                {fixed_code}
                
                Respond in JSON:
                {{
                    "solves_intended_problem": true/false,
                    "actual_problem_solved": "description of what the code actually does",
                    "mismatch_explanation": "explanation if there's a mismatch"
                }}
                """
                try:
                    problem_check = programming_model.generate_content(problem_check_prompt)
                    problem_analysis = json.loads(problem_check.text.replace("```json", "").replace("```", "").strip())
                    
                    if not problem_analysis.get("solves_intended_problem"):
                        # Code is valid but solves the wrong problem. Assign 0 and give specific feedback.
                        justification = (
                            f"P{i+1}: This code does not solve the assigned problem. "
                            f"It appears to be a valid solution for: '{problem_analysis.get('actual_problem_solved', 'an unknown problem')}'. "
                            f"Reason: {problem_analysis.get('mismatch_explanation', 'No explanation provided.')}"
                        )
                        all_justifications.append(justification)
                        total_score += 0.0 # Explicitly add 0
                        continue # Skip to the next program

                    passed_cases = _run_code_in_docker(fixed_code, language, test_cases)
                    score = passed_cases / len(test_cases) if test_cases else 0.0
                    
                    # Add detailed test case feedback
                    test_results = _evaluate_test_cases(fixed_code, language, test_cases)
                    test_feedback = "\n".join([
                        f"Test {idx+1}: {'✓' if result['passed'] else '✗'} "
                        f"Input: {result['input']} | "
                        f"Expected: {result['expected']} | "
                        f"Got: {result['actual']} | "
                        f"{result.get('error_message', '')}"
                        for idx, result in enumerate(test_results)
                    ])
                    
                    all_justifications.append(
                        f"P{i+1}: Passed {passed_cases}/{len(test_cases)} tests for '{part_question}'.\n"
                        f"Detailed Results:\n{test_feedback}"
                    )
                except Exception as e:
                    print(f"Problem analysis failed: {e}")
                    all_justifications.append(f"P{i+1}: Analysis failed during problem verification.")
            else:
                # Gemini-only evaluation for code without input
                prompt = f"""
                Evaluate the correctness of the following {language} program 
                against ONLY this part of the assignment:

                Part: {part_question}

                Provide JSON with "score" (0.0 to 1.0) and "justification".
                Code:
                {fixed_code}
                """
                try:
                    response = programming_model.generate_content(prompt)
                    result = json.loads(response.text.replace("```json", "").replace("```", "").strip())
                    score = result.get("score", 0.0)
                    justification = result.get('justification', 'Gemini evaluation completed.')
                    all_justifications.append(f"P{i+1}: {justification}")
                except Exception as e:
                    print(f"Gemini-only analysis failed: {e}")
                    all_justifications.append(f"P{i+1}: Gemini-only analysis failed.")

            total_score += score

        except Exception as e:
            print(f"Critical error during analysis of program {i+1}: {e}")
            all_justifications.append(f"P{i+1}: Analysis failed.")
            continue

    # --- Step 4: Mark missing parts ---
    if len(parts) > mapped_count:
        for j in range(mapped_count, len(parts)):
            all_justifications.append(f"Part {j+1} ('{parts[j][:50]}...'): No program submitted.")

    # --- Step 5: Final aggregation and summary remark ---
    final_summary = _generate_final_summary(all_justifications, question)
    final_score = total_score / mapped_count if mapped_count else 0.0
    detailed_justification = " | ".join(all_justifications)
    final_justification = f"{detailed_justification} | Final Remark: {final_summary}"

    return {'score': final_score, 'justification': final_justification}


# ----------------- HELPERS -----------------

def _requires_input(code: str) -> bool:
    patterns = ["input(", "scanf", "cin", "readLine", "Scanner"]
    return any(pat in code for pat in patterns)


def _detect_language(code: str) -> str:
    """Ask Gemini to detect language, then normalize."""
    prompt = (
        "Detect the programming language of the following code. "
        "Respond with one word only: Python, Java, C, C++. "
        f"\n\nCode:\n{code}"
    )
    response = programming_model.generate_content(prompt)
    lang = response.text.strip().lower()
    print(f"⚡ Raw Gemini language detection: '{lang}'")   # DEBUG

    # normalize variants
    if any(word in lang for word in ["cpp", "c++", "c plus plus"]):
        return "c++"
    if lang.startswith("python"):
        return "python"
    if lang.startswith("java"):
        return "java"
    if lang == "c" or "c lang" in lang:
        return "c"
    return "unsupported"


def _fix_code(code: str, language: str) -> str:
    prompt = f"Fix OCR errors in the following {language} code. Provide only corrected code, no explanation.\n\n{code}"
    response = programming_model.generate_content(prompt)
    cleaned = response.text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def _generate_test_cases(question: str, language: str) -> list:
    prompt = f"""
    Based on the following programming sub-question, generate 5 test cases.
    Note: Accept both True/False and descriptive answers like "X is prime" or "X is not prime".
    Respond as a JSON list: [{{"input": "...", "expected_output": "..."}}].
    Sub-question: {question}
    Language: {language}
    """
    try:
        response = programming_model.generate_content(prompt)
        json_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_text)
    except Exception as e:
        print(f"Failed to generate test cases: {e}")
        return []


def _run_code_in_docker(code: str, language: str, test_cases: list) -> int:
    """
    Runs student code in a sandboxed Docker container against a set of test cases,
    and normalizes the output to handle formatting differences.
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException:
        raise ConnectionError("Docker is not running. Please start the Docker daemon.")

    # Normalize language string
    language = (language or "").strip().lower()

    passed_count = 0

    for case in test_cases:
        sanitized_input = str(case.get('input', '')).replace("'", "'\\''")

        image, file_name, run_command = None, None, None

        if language == "python":
            image = "python:3.9-slim"
            file_name = "student_code.py"
            run_command = ["sh", "-c", f"echo '{sanitized_input}' | python -u /app/{file_name}"]

        elif language == "c++":
            image = "gcc:latest"
            file_name = "student_code.cpp"
            run_command = ["sh", "-c", f"g++ /app/{file_name} -o /app/program && echo '{sanitized_input}' | /app/program"]

        elif language == "c":
            image = "gcc:latest"
            file_name = "student_code.c"
            run_command = ["sh", "-c", f"gcc /app/{file_name} -o /app/program && echo '{sanitized_input}' | /app/program"]

        elif language == "java":
            image = "openjdk:17-slim-bullseye"
            file_name = "Main.java"
            run_command = ["sh", "-c", f"javac /app/{file_name} && echo '{sanitized_input}' | java -cp /app Main"]

        # If still None → skip gracefully instead of crashing
        if not file_name:
            print(f"⚠️ Unsupported or unknown language '{language}' → skipping execution.")
            continue

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, file_name)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            try:
                output = client.containers.run(
                    image,
                    command=run_command,
                    volumes={temp_dir: {'bind': '/app', 'mode': 'rw'}},
                    working_dir="/app",
                    remove=True,
                    network_disabled=True,
                    mem_limit='256m'
                )

                # Normalize outputs
                sanitized_output = output.decode('utf-8').strip().lower()
                sanitized_expected = str(case.get('expected_output', '')).strip().lower()

                # Try number comparison if expected is a digit
                if sanitized_expected.isdigit():
                    import re
                    match = re.search(r'\d+', sanitized_output)
                    if match and match.group(0) == sanitized_expected:
                        passed_count += 1
                        continue

                if sanitized_output == sanitized_expected:
                    passed_count += 1
                print ( "  " )

            except docker.errors.ContainerError as e:
                print(f"Execution failed for a test case. Container error: {e.stderr.decode('utf-8')}")
                continue
            except Exception as e:
                print(f"An unknown error occurred during execution: {e}")
                continue

    return passed_count




def _split_programs(ocr_text: str) -> list:
    if not programming_model or not ocr_text.strip():
        return []
    prompt = f"""
    Split the following text into distinct complete programs.
    Respond as JSON: {{"programs": ["code1", "code2", ...]}}
    ---
    {ocr_text}
    """
    try:
        response = programming_model.generate_content(prompt)
        json_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_text).get("programs", [])
    except Exception:
        return [ocr_text]


def _split_question_into_parts(question: str) -> list:
    """Split a compound question into multiple sub-parts."""
    if not programming_model or not question.strip():
        return [question]
    prompt = f"""
    The following programming question may have multiple sub-parts or scenarios.
    Split it into distinct parts. 
    Respond as JSON: {{"parts": ["...", "..."]}}
    ---
    {question}
    """
    try:
        response = programming_model.generate_content(prompt)
        json_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_text).get("parts", [question])
    except Exception:
        return [question]


def _evaluate_test_cases(code: str, language: str, test_cases: list) -> list:
    """
    Evaluates each test case and returns detailed results including what went wrong.
    """
    results = []
    client = docker.from_env()

    for case in test_cases:
        result = {
            'input': case.get('input', ''),
            'expected': case.get('expected_output', ''),
            'passed': False,
            'actual': '',
            'error_message': ''
        }

        sanitized_input = str(case.get('input', '')).replace("'", "'\\''")

        # Docker configuration (same as in _run_code_in_docker)
        image, file_name, run_command = None, None, None
        
        if language == "python":
            image = "python:3.9-slim"
            file_name = "student_code.py"
            run_command = ["sh", "-c", f"echo '{sanitized_input}' | python -u /app/{file_name}"]
        elif language == "c++":
            image = "gcc:latest"
            file_name = "student_code.cpp"
            run_command = ["sh", "-c", f"g++ /app/{file_name} -o /app/program && echo '{sanitized_input}' | /app/program"]
        elif language == "c":
            image = "gcc:latest"
            file_name = "student_code.c"
            run_command = ["sh", "-c", f"gcc /app/{file_name} -o /app/program && echo '{sanitized_input}' | /app/program"]
        elif language == "java":
            image = "openjdk:17-slim-bullseye"
            file_name = "Main.java"
            run_command = ["sh", "-c", f"javac /app/{file_name} && echo '{sanitized_input}' | java -cp /app Main"]

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, file_name)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            try:
                output = client.containers.run(
                    image,
                    command=run_command,
                    volumes={temp_dir: {'bind': '/app', 'mode': 'rw'}},
                    working_dir="/app",
                    remove=True,
                    network_disabled=True,
                    mem_limit='256m'
                )

                result['actual'] = output.decode('utf-8').strip()
                
                # More flexible output comparison
                sanitized_output = result['actual'].lower()
                sanitized_expected = str(result['expected']).strip().lower()

                # Check for semantic correctness rather than exact format
                is_prime_indicators = {
                    True: ["is prime", "is a prime", "prime number", "true"],
                    False: ["not prime", "not a prime", "composite", "false"]
                }

                expected_prime = sanitized_expected.lower() in ["true", "1"]
                
                if expected_prime:
                    result['passed'] = any(indicator in sanitized_output.lower() 
                                        for indicator in is_prime_indicators[True])
                else:
                    result['passed'] = any(indicator in sanitized_output.lower() 
                                        for indicator in is_prime_indicators[False])

                if not result['passed']:
                    result['error_message'] = "Output indicates wrong primality"
                else:
                    result['error_message'] = ""

            except docker.errors.ContainerError as e:
                result['error_message'] = f"Runtime Error: {e.stderr.decode('utf-8')}"
            except Exception as e:
                result['error_message'] = f"Execution Error: {str(e)}"

        results.append(result)

    return results

def _generate_final_summary(justifications: list, original_question: str) -> str:
    """Uses Gemini to generate a final summary remark based on part-by-part justifications."""
    if not programming_model or not justifications:
        return "Overall evaluation complete."

    # Format the detailed feedback for the prompt
    detailed_feedback = "\n- ".join(justifications)

    prompt = f"""
    As an AI teaching assistant, you have evaluated a student's programming submission part-by-part.
    Now, provide a single, concise summary remark (one or two sentences) of the student's overall performance.
    This remark should synthesize the key points from the detailed evaluation. Do not mention the score.

    Original Question:
    "{original_question}"

    Detailed Part-by-Part Evaluation:
    - {detailed_feedback}

    ---
    Provide only the final summary text, without any introductory phrases like "The student...".
    For example: "The solution correctly handles basic test cases but fails on edge cases like zero or negative numbers."
    or "While the main logic for primality is correct, the submission was incomplete and missed several requirements."
    or "The submitted code solves for odd/even numbers instead of the requested prime number problem."
    """
    try:
        response = programming_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Failed to generate final summary: {e}")
        return "Could not generate a final summary."

