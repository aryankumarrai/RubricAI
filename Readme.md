# RubricAI: AI-driven Automated Assignment Evaluator

RubricAI is a sophisticated web application designed to automate the grading and plagiarism analysis of Google Classroom assignments. It leverages Google's Generative AI, the Vision API, and a robust background task queue to provide a seamless and efficient experience for instructors.

## ✨ Key Features

* **🤖 AI-Powered Grading**: Utilizes Gemini 1.5 Pro for nuanced analysis of both theoretical and programming submissions.
* **🛡️ Secure Docker Execution**: Safely runs and tests student programming code in sandboxed Docker containers.
* **🔍 Advanced Plagiarism Detection**:
    * **Theory**: Uses semantic similarity analysis to detect conceptual plagiarism, not just keyword matching.
    * **Programming**: Normalizes code via Abstract Syntax Trees (AST) to find structural similarities, making it robust against simple variable renaming.
* **🔗 Full Google Integration**: Authenticates securely with Google OAuth and seamlessly integrates with Google Classroom and Google Drive APIs.
* **⚡ Asynchronous Processing**: Employs a Celery task queue with Redis to handle long-running analyses in the background, ensuring the UI remains fast and responsive.
* **📊 Comprehensive Reporting**: Generates easy-to-read reports for individual grades, class mark sheets, and plagiarism scores.
* **📬 Email Delivery**:
  * automatically sends grade reports to students.
  * includes personalized remarks and performance feedback in the email.

## 🛠️ Technology Stack

* **Backend**: Flask, Celery, SQLAlchemy
* **Database**: SQLite (for development)
* **Task Queue**: Redis
* **AI & ML**: Google Generative AI (Gemini), Google Cloud Vision, Sentence-Transformers
* **Containerization**: Docker
* **Authentication**: Google OAuth

## 🚀 Getting Started

Follow these instructions to get a local copy up and running.

### Prerequisites

* Python 3.9+
* Docker Desktop installed and running.
* Redis Server installed and running.

    * **MacOS (Homebrew):**
        ```sh
        brew install redis
        brew services start redis
        ```
    * **Linux (APT):**
        ```sh
        sudo apt-get update
        sudo apt-get install redis-server
        redis-server
        ```

### Installation & Setup

1.  **Clone the Repository**
    ```sh
    git clone [https://github.com/your-username/rubric-ai.git](https://github.com/your-username/rubric-ai.git)
    cd rubric-ai
    ```

2.  **Install Dependencies**
    ```sh
    pip install -r requirements.txt
    ```

3.  **Setup Environment Variables**
    * Create a `.env` file in the project root.
    * Add your Google API Key:
        ```env
        GEMINI_API_KEY=AIzaSy...
        ```

4.  **Google OAuth Credentials**
    * Enable the **Google Classroom API** and **Google Drive API** in your Google Cloud Console.
    * Create **OAuth 2.0 Client ID** credentials.
    * Download the `client_secret.json` file and place it in the project root.
    * Add `http://127.0.0.1:5000/callback` as an authorized redirect URI in your Google Cloud Console credentials settings.

## 🏃‍♂️ How to Run

The application requires two separate processes to be running: the Celery worker and the Flask web server.

### 1. Start the Celery Worker

Open a **new terminal** window and run:
```sh
celery -A tasks.celery_app worker --loglevel=info
```

### 2. Run the Flask Application

In your original terminal window, run:
```sh
python app.py
```

### 3. Access RubricAI

Open your browser and navigate to [http://127.0.0.1:5000]

## 📂 Project Structure
``` sh

rubricai/
├── __pycache__/              # cached Python bytecode 
├── instance/
│   └── results.db           # SQLite database
├── static/
│   ├── assets/
│   ├── css/
│   │   ├── dashboard.css
│   │   ├── marksheet.css
│   │   └── result.css
│   └── js/
│       └── dashboard.js
├── templates/
│   ├── dashboard.html
│   ├── index.html
│   ├── mark_sheet.html
│   ├── plagiarism_report.html
│   └── results.html
├── venv/                    # virtual environment
├── .gitignore
├── .env                     # environment variables
├── app.py
├── tasks.py
├── plagiarism_checker.py
├── programming_analyzer.py
├── theory_analyzer.py
├── utils.py
├── smtp_test.py
├── client_secret.json       # ignored, OAuth credentials
├── client_secret2.json
└── requirements.txt


```

