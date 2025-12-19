document.addEventListener('DOMContentLoaded', () => {
    const courseSelect = document.getElementById('course-select');
    const assignmentsContainer = document.getElementById('assignments-container');
    const marksheetContainer = document.getElementById('marksheet-link-container');
    const fullscreenPreloader = document.getElementById('full-screen-preloader');
    const preloaderText = document.querySelector('#full-screen-preloader .loader span');

    // --- Custom Modal Elements ---
    const customConfirmModal = document.getElementById('custom-confirm-modal');
    const customConfirmMsg = document.getElementById('custom-confirm-msg');
    const confirmOkBtn = document.getElementById('custom-confirm-ok');
    const confirmCancelBtn = document.getElementById('custom-confirm-cancel');

    // --- Custom Modal Logic ---
    function customConfirm(message) {
        return new Promise((resolve) => {
            customConfirmMsg.textContent = message;
            customConfirmModal.classList.add('visible');

            confirmOkBtn.onclick = () => {
                customConfirmModal.classList.remove('visible');
                resolve(true);
            };

            confirmCancelBtn.onclick = () => {
                customConfirmModal.classList.remove('visible');
                resolve(false);
            };
        });
    }

    // --- Event Listener for Course Selection ---
    courseSelect.addEventListener('change', async () => {
        const courseId = courseSelect.value;
        marksheetContainer.innerHTML = '';
        if (!courseId) {
            assignmentsContainer.innerHTML = '';
            return;
        }

        marksheetContainer.innerHTML = `<a href="/mark_sheet/${courseId}"><button>View Overall Mark Sheet</button></a>`;
        assignmentsContainer.innerHTML = '<div class="container"><p class="status-message info">Loading assignments...</p></div>';
        
        const response = await fetch(`/api/assignments/${courseId}`);
        const data = await response.json();

        if (data.error) {
            assignmentsContainer.innerHTML = `<div class="container"><p class="status-message error">Error: ${data.error}</p></div>`;
            return;
        }

        assignmentsContainer.innerHTML = '<div class="container"><h2>2. Select an Assignment to Analyze</h2></div>';
        if (data.assignments.length === 0) {
            assignmentsContainer.innerHTML += '<div class="container"><p>No assignments found for this course.</p></div>';
        }

        data.assignments.forEach(assignment => {
            const assignmentDiv = document.createElement('div');
            assignmentDiv.className = 'assignment container';
            assignmentDiv.innerHTML = `
                <h3>${assignment.title}</h3>
                <p><strong>Created:</strong> ${new Date(assignment.creationTime).toLocaleString()}</p>
                <p><strong>Due:</strong> ${assignment.dueDate ? `${assignment.dueDate.day}/${assignment.dueDate.month}/${assignment.dueDate.year}` : 'No due date'}</p>
                <label for="domain-select-${assignment.id}">Select Analysis Domain:</label>
                <select id="domain-select-${assignment.id}">
                    <option value="theory">Theoretical Problem</option>
                    <option value="programming">Programming Problem</option>
                </select>
                <button id="analyze-btn-${assignment.id}" onclick="startAnalysis('${courseId}', '${assignment.id}')">Analyze This Assignment</button>
                <button id="clear-btn-${assignment.id}" class="clear-btn" onclick="clearAnalysis('${courseId}', '${assignment.id}')">Clear Analysis</button>
                <button id="results-btn-${assignment.id}" class="results-btn" onclick="viewResults('${courseId}', '${assignment.id}')">See Results</button>
                <p id="status-${assignment.id}" class="status-message"></p>
            `;
            assignmentsContainer.appendChild(assignmentDiv);
        });
    });

    // --- Preloader Helper Functions ---
    function showPreloader(text = "Fetching...") {
        preloaderText.textContent = text;
        fullscreenPreloader.style.display = 'flex';
        setTimeout(() => fullscreenPreloader.classList.add('visible'), 10);
    }

    function hidePreloader() {
        fullscreenPreloader.classList.remove('visible');
        setTimeout(() => fullscreenPreloader.style.display = 'none', 400);
    }

    // --- Core Functions ---
    async function startAnalysis(courseId, assignmentId) {
        const domainSelect = document.getElementById(`domain-select-${assignmentId}`);
        const statusP = document.getElementById(`status-${assignmentId}`);
        const domain = domainSelect.value;

        showPreloader("Analyzing...");
        statusP.className = 'status-message info';
        statusP.textContent = 'Analyzing all student submissions... This may take a few minutes.';

        try {
            const response = await fetch('/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ course_id: courseId, assignment_id: assignmentId, domain: domain }),
            });
            const result = await response.json();
            
            if (!response.ok) {
                statusP.className = 'status-message error';
                statusP.textContent = `Error: ${result.error || 'Analysis failed.'}`;
            } else {
                statusP.className = 'status-message success';
                statusP.textContent = result.status;
                if (result.redirect) {
                    setTimeout(() => window.location.href = result.redirect, 1000);
                }
            }
        } catch (error) {
            statusP.className = 'status-message error';
            statusP.textContent = 'A network error occurred. Please try again.';
        } finally {
            hidePreloader();
        }
    }
    
    async function clearAnalysis(courseId, assignmentId) {
        const confirmed = await customConfirm('Are you sure you want to clear all analysis for this assignment? This action cannot be undone.');
        if (!confirmed) return;

        const statusP = document.getElementById(`status-${assignmentId}`);
        statusP.className = 'status-message info';
        statusP.textContent = 'Clearing analysis data...';

        try {
            const response = await fetch(`/clear_analysis/${courseId}/${assignmentId}`, { method: 'POST' });
            const result = await response.json();
            
            if (!response.ok) {
                statusP.className = 'status-message error';
                statusP.textContent = `Error: ${result.error || 'Could not clear data.'}`;
            } else {
                statusP.className = 'status-message success';
                statusP.textContent = result.status;
            }
        } catch (error) {
            statusP.className = 'status-message error';
            statusP.textContent = 'A network error occurred while trying to clear data.';
        }
    }

    function viewResults(courseId, assignmentId) {
        showPreloader("Fetching...");
        setTimeout(() => {
            window.location.href = `/results/${courseId}/${assignmentId}`;
        }, 500); // Increased delay to make preloader more visible
    }

    // --- Attach functions to window for inline onclick ---
    window.startAnalysis = startAnalysis;
    window.clearAnalysis = clearAnalysis;
    window.viewResults = viewResults;

    // --- FIX for Back/Forward Cache ---
    window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
            hidePreloader();
        }
    });
});

