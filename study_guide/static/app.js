(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  document.querySelectorAll(".nav-link, .quick-card").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = new URL(link.href, window.location.href);
      if (target.origin !== window.location.origin || target.pathname === window.location.pathname) return;
      event.preventDefault();
      const content = $(".content");
      if (!content) return window.location.assign(target.href);
      content.style.transition = "opacity .12s ease, transform .12s ease";
      content.style.opacity = "0";
      content.style.transform = "translateY(7px)";
      window.setTimeout(() => window.location.assign(target.href), 120);
    });
  });

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  function showMessage(node, message, isError = false) {
    node.hidden = false;
    node.className = isError ? "notice error" : "notice";
    node.textContent = message;
  }

  // Translator page
  const sourceLanguage = $("#source-language");
  const targetLanguage = $("#target-language");
  if (sourceLanguage && targetLanguage) {
    const textTab = $("#text-tab");
    const fileTab = $("#file-tab");
    const textPanel = $("#text-panel");
    const filePanel = $("#file-panel");
    const output = $("#translation-output");
    const status = $("#translation-status");
    const meta = $("#translation-meta");
    const copy = $("#copy-translation");

    textTab.addEventListener("click", () => {
      textPanel.hidden = false;
      filePanel.hidden = true;
      textTab.classList.remove("secondary");
      fileTab.classList.add("secondary");
      textTab.setAttribute("aria-selected", "true");
      fileTab.setAttribute("aria-selected", "false");
    });
    fileTab.addEventListener("click", () => {
      textPanel.hidden = true;
      filePanel.hidden = false;
      fileTab.classList.remove("secondary");
      textTab.classList.add("secondary");
      textTab.setAttribute("aria-selected", "false");
      fileTab.setAttribute("aria-selected", "true");
    });
    $("#swap-languages").addEventListener("click", () => {
      if (sourceLanguage.value === "auto") return;
      const originalSource = sourceLanguage.value;
      sourceLanguage.value = targetLanguage.value;
      targetLanguage.value = originalSource;
    });

    const renderTranslation = (result) => {
      output.textContent = result.translation;
      output.classList.add("ready");
      output.setAttribute("lang", result.target_lang || "en");
      output.setAttribute("dir", result.target_dir || "auto");
      $("#output-title").hidden = false;
      status.textContent = `${result.source_name || "Source"} → ${result.target_name || "Translation"}`;
      meta.textContent = result.filename
        ? `${result.filename} · ${result.chunks || 1} section(s)`
        : (result.notes || []).join(" ");
      copy.hidden = false;
      copy.onclick = async () => {
        await navigator.clipboard.writeText(result.translation);
        copy.textContent = "Copied";
        window.setTimeout(() => { copy.textContent = "Copy translation"; }, 1200);
      };
    };

    $("#translate-text").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const text = $("#source-text").value.trim();
      if (!text) {
        output.textContent = "Add some text before translating.";
        return;
      }
      button.disabled = true;
      button.textContent = "Translating…";
      status.textContent = "Working on your translation";
      try {
        const result = await fetchJson("/api/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, source: sourceLanguage.value, target: targetLanguage.value })
        });
        renderTranslation(result);
      } catch (error) {
        output.textContent = error.message;
        output.classList.remove("ready");
        status.textContent = "Translation unavailable";
      } finally {
        button.disabled = false;
        button.innerHTML = 'Translate text <span aria-hidden="true">→</span>';
      }
    });

    $("#translate-file").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const file = $("#document-file").files[0];
      if (!file) {
        output.textContent = "Choose a PDF, TXT, or Markdown file first.";
        return;
      }
      const form = new FormData();
      form.append("file", file);
      form.append("source", sourceLanguage.value);
      form.append("target", targetLanguage.value);
      button.disabled = true;
      button.textContent = "Translating document…";
      status.textContent = "Your document is being processed";
      try {
        renderTranslation(await fetchJson("/api/document", { method: "POST", body: form }));
      } catch (error) {
        output.textContent = error.message;
        output.classList.remove("ready");
        status.textContent = "Document translation unavailable";
      } finally {
        button.disabled = false;
        button.innerHTML = 'Translate document <span aria-hidden="true">→</span>';
      }
    });
  }

  // Translation of a saved note
  const noteButton = $("#translate-note");
  if (noteButton) {
    noteButton.addEventListener("click", async () => {
      const output = $("#note-translation");
      const text = $("#note-original").textContent;
      noteButton.disabled = true;
      noteButton.textContent = "Translating…";
      try {
        const result = await fetchJson("/api/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            source: "auto",
            target: $("#note-target").value
          })
        });
        output.textContent = result.translation;
        output.classList.add("ready");
        output.setAttribute("lang", result.target_lang || "en");
        output.setAttribute("dir", result.target_dir || "auto");
      } catch (error) {
        output.textContent = error.message;
        output.classList.remove("ready");
      } finally {
        noteButton.disabled = false;
        noteButton.textContent = "Translate note";
      }
    });
  }

  // Generated multi-question quiz sessions
  const quizLanguage = $("#quiz-language");
  if (quizLanguage) {
    const stage = $("#quiz-stage");
    const scoreLabel = $("#quiz-score");
    const status = $("#quiz-status");
    const subjectSelect = $("#quiz-subject");
    const countSelect = $("#quiz-count");
    const startButton = $("#quiz-start");
    const nextButton = $("#next-question");
    let questions = [];
    let currentIndex = 0;
    let score = 0;
    let answered = false;
    let subjectCounts = {};

    function updateCountOptions() {
      const max = subjectSelect.value === "all"
        ? Object.values(subjectCounts).reduce((sum, value) => sum + value, 0)
        : (subjectCounts[subjectSelect.value] || 0);
      const options = [3, 5, 8, 12].filter((value) => value <= max);
      if (max > 0 && !options.length) options.push(max);
      countSelect.replaceChildren();
      options.forEach((value) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = String(value);
        countSelect.append(option);
      });
      startButton.disabled = max === 0;
      if (max === 0) status.textContent = "No questions are available for this subject.";
    }

    async function loadQuizOptions() {
      try {
        const result = await fetchJson(`/api/quizzes?language=${encodeURIComponent(quizLanguage.value)}`);
        subjectCounts = result.subjects.reduce((counts, subject) => {
          counts[subject] = result.quizzes.filter((question) => question.subject === subject).length;
          return counts;
        }, {});
        updateCountOptions();
      } catch (error) {
        status.textContent = error.message;
      }
    }

    function renderQuestion() {
      const current = questions[currentIndex];
      answered = false;
      stage.replaceChildren();
      const subject = document.createElement("div");
      subject.className = "quiz-number";
      subject.textContent = `${current.subject} · Question ${currentIndex + 1} of ${questions.length}`;
      const question = document.createElement("h2");
      question.className = "quiz-question";
      question.textContent = current.question;
      const choices = document.createElement("div");
      choices.className = "answer-grid";
      current.choices.forEach((choice, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "answer-choice";
        button.textContent = choice;
        button.addEventListener("click", () => selectAnswer(button, index, choices));
        choices.append(button);
      });
      const feedback = document.createElement("p");
      feedback.className = "feedback";
      feedback.id = "answer-feedback";
      feedback.setAttribute("aria-live", "polite");
      stage.append(subject, question, choices, feedback);
      stage.classList.add("page-enter");
      scoreLabel.textContent = `Score: ${score}/${questions.length}`;
      nextButton.hidden = true;
    }

    function selectAnswer(selected, index, group) {
      if (answered) return;
      answered = true;
      const current = questions[currentIndex];
      const correct = index === current.answer_index;
      if (correct) score += 1;
      [...group.children].forEach((button, choiceIndex) => {
        button.disabled = true;
        if (choiceIndex === current.answer_index) button.classList.add("correct");
        else if (button === selected) button.classList.add("incorrect");
      });
      const feedback = $("#answer-feedback");
      feedback.className = `feedback ${correct ? "good" : "bad"}`;
      feedback.textContent = `${correct ? "That’s right." : "Not quite."} ${current.explanation}`;
      scoreLabel.textContent = `Score: ${score}/${questions.length}`;
      nextButton.textContent = currentIndex + 1 === questions.length ? "Finish quiz" : "Next question →";
      nextButton.hidden = false;
    }

    $("#quiz-setup").addEventListener("submit", async (event) => {
      event.preventDefault();
      startButton.disabled = true;
      status.textContent = "Generating your quiz…";
      stage.textContent = "Preparing questions…";
      nextButton.hidden = true;
      try {
        const result = await fetchJson("/api/quizzes/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            language: quizLanguage.value,
            subject: subjectSelect.value,
            count: Number(countSelect.value)
          })
        });
        questions = result.questions;
        currentIndex = 0;
        score = 0;
        status.textContent = `${result.count}-question quiz ready.`;
        renderQuestion();
      } catch (error) {
        stage.textContent = error.message;
        status.textContent = "Could not generate the quiz.";
      } finally {
        startButton.disabled = false;
      }
    });

    nextButton.addEventListener("click", () => {
      currentIndex += 1;
      if (currentIndex >= questions.length) {
        stage.replaceChildren();
        const result = document.createElement("h2");
        result.textContent = `Quiz complete: ${score} / ${questions.length}`;
        const summary = document.createElement("p");
        summary.className = "lead";
        summary.textContent = score === questions.length
          ? "Excellent work. Try another session to keep practicing."
          : "Review the explanations, then generate another session when you are ready.";
        stage.append(result, summary);
        status.textContent = "Session complete.";
        nextButton.hidden = true;
        return;
      }
      renderQuestion();
    });

    subjectSelect.addEventListener("change", updateCountOptions);
    quizLanguage.addEventListener("change", loadQuizOptions);
    loadQuizOptions();

    const jotformStatus = $("#jotform-status");
    if (jotformStatus) {
      fetchJson("/api/jotform/form")
        .then((form) => {
          if (!form.connected) {
            jotformStatus.textContent = form.error;
            return;
          }
          $("#jotform-title").textContent = form.title;
          jotformStatus.textContent = `Connected · ${form.question_count} form fields available through the Jotform API.`;
          const questionList = $("#jotform-questions");
          form.questions.forEach((text) => {
            const item = document.createElement("li");
            item.textContent = text;
            questionList.append(item);
          });
        })
        .catch((error) => { jotformStatus.textContent = error.message; });
    }
  }

  // Multilingual public university links
  const helpLanguage = $("#help-language");
  if (helpLanguage) {
    const results = $("#help-results");
    async function loadHelp() {
      results.textContent = "Loading student information…";
      try {
        const data = await fetchJson(`/api/university-info?language=${encodeURIComponent(helpLanguage.value)}`);
        results.replaceChildren();
        data.items.forEach((item) => {
          const article = document.createElement("article");
          article.className = "faq-item";
          const top = document.createElement("div");
          top.className = "faq-top";
          const icon = document.createElement("span");
          icon.className = "faq-icon";
          icon.textContent = item.icon;
          const content = document.createElement("div");
          const category = document.createElement("div");
          category.className = "category";
          category.textContent = item.category;
          const title = document.createElement("h3");
          title.textContent = item.title;
          const body = document.createElement("p");
          body.textContent = item.body;
          const source = document.createElement("a");
          source.className = "link-button";
          source.href = item.source_url;
          source.target = "_blank";
          source.rel = "noopener noreferrer";
          source.textContent = "Open official source →";
          content.append(category, title, body, source);
          top.append(icon, content);
          article.append(top);
          results.append(article);
        });
      } catch (error) {
        const message = document.createElement("div");
        message.className = "notice error";
        message.textContent = error.message;
        results.replaceChildren(message);
      }
    }
    helpLanguage.addEventListener("change", loadHelp);
    if (helpLanguage.value !== "en") loadHelp();
  }

  // OpenAlex open-access research catalog
  const librarySearch = $("#library-search");
  if (librarySearch) {
    const queryInput = $("#library-query");
    const results = $("#library-results");
    const status = $("#library-status");
    const submit = $("#library-submit");

    librarySearch.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      status.textContent = "Searching open-access research…";
      results.replaceChildren();
      try {
        const data = await fetchJson(`/api/library?query=${encodeURIComponent(queryInput.value.trim())}`);
        if (!data.results.length) {
          status.textContent = "No open-access records were found. Try broader keywords.";
          return;
        }
        status.textContent = `${data.results.length} open-access result(s) from OpenAlex.`;
        data.results.forEach((work) => {
          const article = document.createElement("article");
          article.className = "resource-card";
          const label = document.createElement("div");
          label.className = "category";
          label.textContent = [work.journal, work.year].filter(Boolean).join(" · ") || "Open-access research";
          const title = document.createElement("h3");
          title.textContent = work.title;
          const authors = document.createElement("p");
          authors.textContent = work.authors.length ? work.authors.join(", ") : "Author details not listed";
          const link = document.createElement("a");
          link.className = "link-button";
          link.href = work.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "View article or repository →";
          article.append(label, title, authors, link);
          results.append(article);
        });
      } catch (error) {
        status.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });
  }
})();
