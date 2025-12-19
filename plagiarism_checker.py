import ast
from itertools import combinations
from sentence_transformers import SentenceTransformer, util

# Load a pre-trained model for semantic plagiarism.
# This model is lightweight and effective.
print("Loading sentence plagiarism model for plagiarism check...")
try:
    theory_model = SentenceTransformer('all-MiniLM-L6-v2')
    print("Sentence plagiarism model loaded successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: Could not load SentenceTransformer model: {e}")
    theory_model = None

def _normalize_code(code_string: str) -> str:
    """
    Parses code into an Abstract Syntax Tree (AST) and then unparses it.
    This process strips comments and normalizes formatting, variable names, etc.
    It focuses on the structural identity of the code.
    """
    try:
        tree = ast.parse(code_string)
        # Anonymize names to prevent simple variable renames from fooling the check
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                node.id = '_'
            elif isinstance(node, ast.FunctionDef):
                node.name = '_'
            elif isinstance(node, ast.arg):
                node.arg = '_'
        return ast.unparse(tree)
    except (SyntaxError, ValueError):
        # If code can't be parsed, fall back to the original code for comparison.
        return code_string

def check_plagiarism_for_assignment(student_submissions: dict, domain: str) -> list:
    """
    Analyzes submissions for plagiarism using domain-specific strategies.

    Args:
        student_submissions (dict): A dictionary mapping {student_id: submission_text}.
        domain (str): Either 'theory' or 'programming'.

    Returns:
        list: A list of dictionaries, each containing {'student1', 'student2', 'score'}.
    """
    if len(student_submissions) < 2:
        return [] # Not enough submissions to compare

    student_ids = list(student_submissions.keys())
    results = []

    # Create all unique pairs of students to compare
    student_pairs = combinations(student_ids, 2)

    if domain == 'theory':
        if not theory_model:
            print("Skipping theory plagiarism check: model not loaded.")
            return []
            
        print(f"Performing theory plagiarism check on {len(student_submissions)} submissions.")
        # Create embeddings for all submissions at once (more efficient)
        corpus = [student_submissions[sid] for sid in student_ids]
        embeddings = theory_model.encode(corpus, convert_to_tensor=True)
        
        # Compute cosine plagiarism for all pairs
        plagiarism_matrix = util.cos_sim(embeddings, embeddings)

        for i in range(len(student_ids)):
            for j in range(i + 1, len(student_ids)):
                score = plagiarism_matrix[i][j].item()
                results.append({
                    'student1': student_ids[i],
                    'student2': student_ids[j],
                    'score': score
                })

    elif domain == 'programming':
        print(f"Performing programming plagiarism check on {len(student_submissions)} submissions.")
        normalized_codes = {sid: _normalize_code(code) for sid, code in student_submissions.items()}
        
        for student1, student2 in student_pairs:
            # Simple text plagiarism on the *normalized* AST representation
            norm_code1 = normalized_codes[student1]
            norm_code2 = normalized_codes[student2]
            
            # Using a simple sequence matcher for plagiarism score
            from difflib import SequenceMatcher
            plagiarism = SequenceMatcher(None, norm_code1, norm_code2).ratio()
            
            results.append({
                'student1': student1,
                'student2': student2,
                'score': plagiarism
            })

    return results