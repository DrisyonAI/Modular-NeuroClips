/**
 * NeuroClips Interactive Assessment & Quiz Engine
 * Renders multiple-choice and scenario questions, evaluates submissions, provides immediate rationales,
 * tracks attempts, and synchronizes scores with SCORM 1.2 / 2004 gradebook.
 */

class QuizEngine {
  constructor(quizConfig, onCompleteCallback) {
    this.config = quizConfig || {};
    this.onComplete = onCompleteCallback || (() => {});
    this.userAnswers = {}; // { [qId]: selectedValue }
    this.submitted = false;
    this.passingScore = this.config.passingScore || 70;
    this.maxAttempts = this.config.maxAttempts || 3;
    this.allowRetry = this.config.allowRetry !== false;
  }

  /**
   * Renders full quiz markup.
   */
  render(containerEl, previousAttempt = null) {
    if (!containerEl) return;
    const questions = this.config.questions || [];
    if (questions.length === 0) {
      containerEl.innerHTML = '';
      return;
    }

    const title = this.config.title || 'Knowledge Check & Assessment';
    const totalQuestions = questions.length;

    let html = `
      <div class="quiz-section">
        <div class="quiz-header-badge">ASSESSMENT</div>
        <h3 class="quiz-title">${esc(title)}</h3>
        <p class="quiz-meta">Answer all questions to verify your understanding. Passing score: <strong>${this.passingScore}%</strong></p>

        <form id="quiz-form" onsubmit="return false;">
          <div class="questions-container">
            ${questions.map((q, idx) => this.renderQuestion(q, idx)).join('')}
          </div>

          <div class="quiz-actions-bar">
            <span id="quiz-count-display" style="font-size: 12px; color: #64748B;">0 of ${totalQuestions} answered</span>
            <button type="button" id="quiz-submit-action-btn" class="quiz-submit-btn" onclick="submitActiveQuiz()">
              Submit &amp; Check Answers
            </button>
          </div>

          <div id="quiz-score-report" class="quiz-score-card">
            <div id="quiz-score-badge" style="font-size: 13px; font-weight: 700;"></div>
            <div id="quiz-score-value" class="quiz-score-num">0%</div>
            <div id="quiz-score-msg" style="font-size: 13px; color: #475569; margin-bottom: 12px;"></div>
            <div id="quiz-retry-container" style="display: none; margin-top: 10px;">
              <button type="button" class="btn-secondary" onclick="resetActiveQuiz()">Retry Quiz</button>
            </div>
          </div>
        </form>
      </div>
    `;

    containerEl.innerHTML = html;

    // Restore previous attempt if passed
    if (previousAttempt && previousAttempt.passed) {
      this.submitted = true;
      const scoreCard = document.getElementById('quiz-score-report');
      if (scoreCard) {
        scoreCard.classList.add('active');
        const badge = document.getElementById('quiz-score-badge');
        badge.innerText = 'PASSED';
        badge.style.color = '#10B981';
        const val = document.getElementById('quiz-score-value');
        val.innerText = `${previousAttempt.bestScore}%`;
        val.className = 'quiz-score-num pass';
        document.getElementById('quiz-submit-action-btn').disabled = true;
        document.getElementById('quiz-submit-action-btn').innerText = 'Assessment Completed';
      }
    }
  }

  renderQuestion(q, idx) {
    const qId = q.id || `q_${idx}`;
    const typeLabel = q.type ? q.type.toUpperCase() : 'KNOWLEDGE';
    const topicLabel = q.source_topic || q.category || '';
    const rawOptions = q.options || [];

    // Normalize options format: array of strings OR array of { key, text }
    const options = rawOptions.map((opt, oIdx) => {
      if (typeof opt === 'string') {
        const letter = String.fromCharCode(65 + oIdx);
        return { key: letter, text: opt };
      }
      return { key: opt.key || String(oIdx), text: opt.text };
    });

    return `
      <div class="question-card" id="q-card-${esc(qId)}">
        <div class="question-card-top">
          <span class="question-type-tag">${esc(typeLabel)} CHECK</span>
          ${topicLabel ? `<span style="font-size: 11px; color: #94A3B8;">${esc(topicLabel)}</span>` : ''}
        </div>
        <p class="question-text">${idx + 1}. ${esc(q.text || q.question)}</p>
        <div class="options-list">
          ${options.map(opt => `
            <label class="option-label" id="label-${esc(qId)}-${esc(opt.key)}">
              <input type="radio" name="radio_${esc(qId)}" value="${esc(opt.key)}" class="option-radio" onchange="recordActiveQuizAnswer('${esc(qId)}', '${esc(opt.key)}')" />
              <span><strong>${esc(opt.key)}.</strong> ${esc(opt.text)}</span>
            </label>
          `).join('')}
        </div>
        <div id="rationale-${esc(qId)}" class="rationale-card"></div>
      </div>
    `;
  }

  recordAnswer(qId, key) {
    this.userAnswers[qId] = key;
    const questions = this.config.questions || [];
    const count = Object.keys(this.userAnswers).length;
    const countEl = document.getElementById('quiz-count-display');
    if (countEl) {
      countEl.innerText = `${count} of ${questions.length} answered`;
    }

    // Highlight selected option label
    const card = document.getElementById(`q-card-${qId}`);
    if (card) {
      card.querySelectorAll('.option-label').forEach(lbl => lbl.classList.remove('selected'));
      const activeLabel = document.getElementById(`label-${qId}-${key}`);
      if (activeLabel) activeLabel.classList.add('selected');
    }
  }

  submit() {
    if (this.submitted) return;
    const questions = this.config.questions || [];
    if (questions.length === 0) return;

    let correctCount = 0;

    questions.forEach(q => {
      const qId = q.id || '';
      const userChoice = this.userAnswers[qId];
      const rationaleEl = document.getElementById(`rationale-${qId}`);

      // Determine correct answer key (could be index or letter or string)
      let correctKey = q.answer !== undefined ? q.answer : q.correct_key;
      if (typeof correctKey === 'number') {
        correctKey = String.fromCharCode(65 + correctKey);
      }

      const isCorrect = String(userChoice).toUpperCase() === String(correctKey).toUpperCase();
      if (isCorrect) correctCount++;

      if (rationaleEl) {
        if (isCorrect) {
          rationaleEl.className = 'rationale-card correct';
          rationaleEl.innerHTML = `<strong>✓ Correct!</strong> ${esc(q.feedback || q.rationale || 'Good job!')}`;
        } else {
          rationaleEl.className = 'rationale-card incorrect';
          rationaleEl.innerHTML = `<strong>✗ Incorrect.</strong> Correct answer: <strong>${esc(correctKey)}</strong><br>${esc(q.feedback || q.rationale || '')}`;
        }
      }
    });

    const scorePercent = Math.round((correctCount / questions.length) * 100);
    const passed = scorePercent >= this.passingScore;
    this.submitted = true;

    // Show score report card
    const scoreCard = document.getElementById('quiz-score-report');
    if (scoreCard) {
      scoreCard.classList.add('active');
      const badge = document.getElementById('quiz-score-badge');
      const val = document.getElementById('quiz-score-value');
      const msg = document.getElementById('quiz-score-msg');

      if (passed) {
        badge.innerText = 'PASSED';
        badge.style.color = '#10B981';
        val.innerText = `${scorePercent}%`;
        val.className = 'quiz-score-num pass';
        msg.innerText = `Great job! You answered ${correctCount} of ${questions.length} questions correctly.`;
      } else {
        badge.innerText = 'NEEDS REVIEW';
        badge.style.color = '#E5252A';
        val.innerText = `${scorePercent}%`;
        val.className = 'quiz-score-num fail';
        msg.innerText = `You scored ${scorePercent}%. A score of ${this.passingScore}% is required to pass.`;

        if (this.allowRetry) {
          const retryContainer = document.getElementById('quiz-retry-container');
          if (retryContainer) retryContainer.style.display = 'block';
        }
      }
    }

    const submitBtn = document.getElementById('quiz-submit-action-btn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerText = 'Submitted';
    }

    // Trigger onComplete callback to sync with store and LMS
    this.onComplete(scorePercent, passed, this.userAnswers);
  }

  reset() {
    this.submitted = false;
    this.userAnswers = {};
    const form = document.getElementById('quiz-form');
    if (form) form.reset();

    const scoreCard = document.getElementById('quiz-score-report');
    if (scoreCard) scoreCard.classList.remove('active');

    const submitBtn = document.getElementById('quiz-submit-action-btn');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = 'Submit & Check Answers';
    }

    document.querySelectorAll('.option-label').forEach(l => l.classList.remove('selected'));
    document.querySelectorAll('.rationale-card').forEach(r => {
      r.className = 'rationale-card';
      r.innerHTML = '';
    });

    const countEl = document.getElementById('quiz-count-display');
    if (countEl) countEl.innerText = `0 of ${(this.config.questions || []).length} answered`;
  }
}

// Global hook for events
let activeQuizInstance = null;

window.recordActiveQuizAnswer = function(qId, key) {
  if (activeQuizInstance) activeQuizInstance.recordAnswer(qId, key);
};

window.submitActiveQuiz = function() {
  if (activeQuizInstance) activeQuizInstance.submit();
};

window.resetActiveQuiz = function() {
  if (activeQuizInstance) activeQuizInstance.reset();
};

window.QuizEngine = QuizEngine;
window.setActiveQuizInstance = function(inst) {
  activeQuizInstance = inst;
};
