let jobId = null;
let sourceFormat = null;
let gaps = [];
let edits = [];

const uploadForm = document.getElementById("upload-form");
const uploadStatus = document.getElementById("upload-status");
const resultsSection = document.getElementById("results-section");
const noGapsMessage = document.getElementById("no-gaps-message");
const gapsList = document.getElementById("gaps-list");
const editsList = document.getElementById("edits-list");
const generateButton = document.getElementById("generate-button");
const generateStatus = document.getElementById("generate-status");
const downloadLink = document.getElementById("download-link");

function renderGaps() {
  gapsList.innerHTML = "";
  noGapsMessage.hidden = gaps.length > 0;
  for (const gap of gaps) {
    const div = document.createElement("div");
    div.className = "gap-item";
    div.dataset.requirement = gap.requirement;
    div.innerHTML = `
      <p><strong>Missing:</strong> ${escapeHtml(gap.requirement)}</p>
      <p>${escapeHtml(gap.question_to_user)}</p>
      <textarea rows="2" placeholder="Your answer (leave blank to skip)"></textarea>
    `;
    gapsList.appendChild(div);
  }
}

function renderEdits() {
  editsList.innerHTML = "";
  for (const edit of edits) {
    const div = document.createElement("div");
    div.className = "edit-item";
    div.dataset.editId = edit.edit_id;
    const disabled = edit.requires_user_input ? "disabled" : "";
    const checked = edit.requires_user_input ? "" : "checked";
    div.innerHTML = `
      <div class="edit-header">
        <input type="checkbox" ${checked} ${disabled} />
        <strong>${edit.type.replace("_", " ")}</strong>
      </div>
      <p class="rationale">${escapeHtml(edit.rationale)}</p>
      <textarea rows="2">${escapeHtml(edit.new_text)}</textarea>
    `;
    editsList.appendChild(div);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function extractErrorMessage(response, fallback) {
  try {
    const body = await response.json();
    if (body && body.detail) return body.detail;
  } catch {
    // response wasn't JSON — fall through to the generic message
  }
  return `${fallback} (${response.status})`;
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("resume-file");
  const jobDescription = document.getElementById("job-description").value;

  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("resume", fileInput.files[0]);
  formData.append("job_description", jobDescription);

  uploadStatus.textContent = "Analyzing resume against job description...";
  const submitButton = uploadForm.querySelector("button");
  submitButton.disabled = true;

  try {
    const response = await fetch("/api/jobs", { method: "POST", body: formData });
    if (!response.ok) {
      throw new Error(await extractErrorMessage(response, "Analysis failed"));
    }
    const data = await response.json();
    jobId = data.job_id;
    sourceFormat = data.source_format;
    gaps = data.gaps;
    edits = data.suggested_edits;

    uploadStatus.textContent = "";
    resultsSection.hidden = false;
    renderGaps();
    renderEdits();
  } catch (err) {
    uploadStatus.textContent = err.message;
  } finally {
    submitButton.disabled = false;
  }
});

generateButton.addEventListener("click", async () => {
  generateButton.disabled = true;
  downloadLink.hidden = true;
  generateStatus.textContent = "Submitting answers...";

  try {
    const answers = [];
    for (const gapDiv of gapsList.children) {
      const answer = gapDiv.querySelector("textarea").value.trim();
      if (answer) {
        answers.push({ requirement: gapDiv.dataset.requirement, answer });
      }
    }

    if (answers.length > 0) {
      const answersResponse = await fetch(`/api/jobs/${jobId}/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      if (!answersResponse.ok) {
        throw new Error(await extractErrorMessage(answersResponse, "Submitting answers failed"));
      }
      const answersData = await answersResponse.json();
      edits = answersData.suggested_edits;
      renderEdits();
    }

    generateStatus.textContent = "Generating tailored resume...";

    const acceptedEdits = [];
    for (const editDiv of editsList.children) {
      const checkbox = editDiv.querySelector("input[type=checkbox]");
      if (!checkbox.checked) continue;
      const editId = editDiv.dataset.editId;
      const original = edits.find((e) => e.edit_id === editId);
      const newText = editDiv.querySelector("textarea").value;
      acceptedEdits.push({ ...original, new_text: newText });
    }

    const applyResponse = await fetch(`/api/jobs/${jobId}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted_edits: acceptedEdits }),
    });
    if (!applyResponse.ok) {
      throw new Error(await extractErrorMessage(applyResponse, "Generating resume failed"));
    }
    const applyData = await applyResponse.json();

    generateStatus.textContent =
      applyData.failed_edit_ids.length > 0
        ? `Done, with ${applyData.failed_edit_ids.length} edit(s) that couldn't be applied automatically.`
        : "Done.";
    downloadLink.href = applyData.download_url;
    downloadLink.hidden = false;
  } catch (err) {
    generateStatus.textContent = err.message;
  } finally {
    generateButton.disabled = false;
  }
});
