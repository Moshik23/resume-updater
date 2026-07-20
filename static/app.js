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
const summarySection = document.getElementById("summary-section");
const summaryContent = document.getElementById("summary-content");
const downloadLink = document.getElementById("download-link");
const summaryDownloadLink = document.getElementById("summary-download-link");
const checklistToggle = document.getElementById("checklist-toggle");
const scoreBefore = document.getElementById("score-before");
const scoreBeforeAfter = document.getElementById("score-before-after");

let lastSummaryMarkdown = null;

function formatScore(value) {
  return `${Math.round(value)}%`;
}

const steps = {
  upload: document.querySelector('.step[data-step="1"]'),
  review: document.querySelector('.step[data-step="2"]'),
  download: document.querySelector('.step[data-step="3"]'),
};

function setStep(name) {
  const order = ["upload", "review", "download"];
  const activeIndex = order.indexOf(name);
  order.forEach((key, index) => {
    steps[key].classList.toggle("is-active", index === activeIndex);
    steps[key].classList.toggle("is-done", index < activeIndex);
  });
}

function setStatus(el, message, state) {
  el.textContent = message;
  if (state) {
    el.dataset.state = state;
  } else {
    delete el.dataset.state;
  }
}

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
  // renderEdits() is called again every time /answers responds -- including
  // when it's a no-op resubmission of an already-answered gap (its textarea
  // still has text in it), which happens on every subsequent "Generate"
  // click. Rebuilding from scratch with the old default logic would silently
  // reset every checkbox and any manually-edited wording back to defaults,
  // undoing whatever the user had toggled. Capture the current state first
  // and preserve it, except for edits that just transitioned out of
  // "requires user input" this exact cycle -- those get the fresh default
  // (checked, freshly-phrased text) the same way a first render would.
  const previousState = new Map();
  for (const editDiv of editsList.children) {
    previousState.set(editDiv.dataset.editId, {
      checked: editDiv.querySelector("input[type=checkbox]").checked,
      wasDisabled: editDiv.querySelector("input[type=checkbox]").disabled,
      text: editDiv.querySelector("textarea").value,
    });
  }

  editsList.innerHTML = "";
  for (const edit of edits) {
    const div = document.createElement("div");
    div.className = "edit-item";
    div.dataset.editId = edit.edit_id;
    const prior = previousState.get(edit.edit_id);
    const justResolved = !!(prior && prior.wasDisabled && !edit.requires_user_input);
    const useDefault = !prior || justResolved;
    const disabled = edit.requires_user_input ? "disabled" : "";
    const checked = (useDefault ? !edit.requires_user_input : prior.checked) ? "checked" : "";
    const textValue = useDefault ? edit.new_text : prior.text;
    div.innerHTML = `
      <div class="edit-header">
        <input type="checkbox" ${checked} ${disabled} />
        <strong>${edit.type.replace("_", " ")}</strong>
      </div>
      <p class="rationale">${escapeHtml(edit.rationale)}</p>
      <textarea rows="2">${escapeHtml(textValue)}</textarea>
    `;
    editsList.appendChild(div);
  }
}

// Renders the small, controlled markdown subset that app/summary.py emits
// (# / ## headings, "- " bullets with one level of nested "  - " bullets,
// and **bold**). Not a general-purpose markdown parser.
//
// When withCheckboxes is true, each top-level bullet (one applied change,
// gap, or matched requirement) is wrapped in a checkbox label so a user
// editing their resume by hand can tick items off as they go. Detail
// bullets nested under a top-level item stay outside the checkbox label —
// only the top-level item itself is checkable.
function renderSummaryMarkdown(markdown, withCheckboxes) {
  const lines = markdown.split("\n").map((line) => line.trimEnd());
  let html = "";
  let inTopList = false;
  let inNestedList = false;
  let topItemOpen = false;
  let topLabelOpen = false;

  const closeTopLabel = () => {
    if (topLabelOpen) {
      html += "</span></label>";
      topLabelOpen = false;
    }
  };
  const closeNestedList = () => {
    if (inNestedList) {
      html += "</ul>";
      inNestedList = false;
    }
  };
  const closeTopItem = () => {
    closeNestedList();
    closeTopLabel();
    if (topItemOpen) {
      html += "</li>";
      topItemOpen = false;
    }
  };
  const closeTopList = () => {
    closeTopItem();
    if (inTopList) {
      html += "</ul>";
      inTopList = false;
    }
  };

  const inlineFormat = (text) =>
    escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  for (const line of lines) {
    if (line.startsWith("# ")) {
      closeTopList();
      continue; // top-level title is already shown as the section heading
    }
    if (line.startsWith("## ")) {
      closeTopList();
      html += `<h2>${inlineFormat(line.slice(3))}</h2>`;
      continue;
    }
    const nestedMatch = line.match(/^ {2}- (.*)$/);
    const topMatch = line.match(/^- (.*)$/);
    if (nestedMatch) {
      closeTopLabel(); // detail bullets sit outside the checkbox label
      if (!inNestedList) {
        html += "<ul>";
        inNestedList = true;
      }
      html += `<li>${inlineFormat(nestedMatch[1])}</li>`;
    } else if (topMatch) {
      closeTopItem();
      if (!inTopList) {
        html += "<ul>";
        inTopList = true;
      }
      if (withCheckboxes) {
        html += `<li><label class="checklist-item"><input type="checkbox" /><span>${inlineFormat(topMatch[1])}`;
        topLabelOpen = true;
      } else {
        html += `<li>${inlineFormat(topMatch[1])}`;
      }
      topItemOpen = true;
    }
  }
  closeTopList();
  return html;
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

  setStatus(uploadStatus, "Analyzing resume against job description...");
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
    scoreBefore.textContent = formatScore(data.match_score_before);

    setStatus(uploadStatus, "");
    resultsSection.hidden = false;
    setStep("review");
    renderGaps();
    renderEdits();
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus(uploadStatus, err.message, "error");
  } finally {
    submitButton.disabled = false;
  }
});

generateButton.addEventListener("click", async () => {
  generateButton.disabled = true;
  summarySection.hidden = true;
  downloadLink.hidden = true;
  summaryDownloadLink.hidden = true;
  setStatus(generateStatus, "Submitting answers...");

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

    setStatus(generateStatus, "Generating tailored resume...");

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

    setStatus(
      generateStatus,
      applyData.failed_edit_ids.length > 0
        ? `Done, with ${applyData.failed_edit_ids.length} edit(s) that couldn't be applied automatically — see the summary below.`
        : "Done.",
      "success",
    );
    downloadLink.href = applyData.download_url;
    downloadLink.hidden = false;

    if (applyData.summary_markdown) {
      lastSummaryMarkdown = applyData.summary_markdown;
      summaryContent.innerHTML = renderSummaryMarkdown(lastSummaryMarkdown, checklistToggle.checked);
      summaryDownloadLink.href = applyData.summary_download_url;
      summaryDownloadLink.hidden = false;
      summarySection.hidden = false;

      if (applyData.match_score_before != null && applyData.match_score_after != null) {
        scoreBeforeAfter.innerHTML =
          `${formatScore(applyData.match_score_before)} → ` +
          `<span class="score-after">${formatScore(applyData.match_score_after)}</span>`;
      }
    }

    setStep("download");
    summarySection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus(generateStatus, err.message, "error");
  } finally {
    generateButton.disabled = false;
  }
});

checklistToggle.addEventListener("change", () => {
  if (lastSummaryMarkdown) {
    summaryContent.innerHTML = renderSummaryMarkdown(lastSummaryMarkdown, checklistToggle.checked);
  }
});
