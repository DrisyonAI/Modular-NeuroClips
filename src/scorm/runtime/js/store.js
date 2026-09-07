/**
 * NeuroClips State Store
 * Manages versioned, serializable learner state with compact SCORM suspend_data serialization,
 * budget enforcement, and localStorage fallback.
 */

class LearnerStore {
  constructor(courseId = 'course-001') {
    this.schemaVersion = 1;
    this.courseId = courseId;
    this.currentModuleId = '';
    this.currentLessonId = '';
    this.startedAt = new Date().toISOString();
    this.lastSavedAt = new Date().toISOString();
    this.lessons = {}; // { [lessonId]: { status, visited, timeSeconds, videoWatchedRatio, interactions, quiz } }
    this.isDirty = false;
    this.maxSuspendBytes = 3800; // Safe budget for SCORM 1.2
  }

  /**
   * Initializes or restores store from SCORM suspend_data or localStorage.
   */
  load(scormAdapter) {
    let raw = '';
    if (scormAdapter && scormAdapter.initialized) {
      raw = scormAdapter.getSuspendData();
    }

    if (!raw) {
      try {
        raw = localStorage.getItem(`neuroclips_state_${this.courseId}`);
      } catch (e) {}
    }

    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        this.migrateAndHydrate(parsed);
        console.log('[LearnerStore] Restored learner state:', this);
        return true;
      } catch (err) {
        console.warn('[LearnerStore] Failed to parse suspend_data. Starting fresh session.', err);
      }
    }
    return false;
  }

  /**
   * Schema migration handler.
   */
  migrateAndHydrate(data) {
    if (!data || typeof data !== 'object') return;

    // Handle v1
    this.schemaVersion = data.schemaVersion || 1;
    this.courseId = data.courseId || this.courseId;
    this.currentModuleId = data.currentModuleId || '';
    this.currentLessonId = data.currentLessonId || '';
    this.startedAt = data.startedAt || this.startedAt;
    this.lastSavedAt = data.lastSavedAt || new Date().toISOString();
    this.lessons = data.lessons || {};
  }

  /**
   * Serializes state to compact JSON, pruning detailed past logs if over budget.
   */
  serialize() {
    this.lastSavedAt = new Date().toISOString();
    let payload = {
      v: this.schemaVersion,
      cId: this.courseId,
      mId: this.currentModuleId,
      lId: this.currentLessonId,
      ts: this.startedAt,
      lu: this.lastSavedAt,
      ls: this.lessons
    };

    let json = JSON.stringify(payload);
    if (json.length > this.maxSuspendBytes) {
      // Prune detailed question answers from old quizzes to stay within budget
      const clonedLessons = JSON.parse(JSON.stringify(this.lessons));
      for (const key of Object.keys(clonedLessons)) {
        if (clonedLessons[key].quiz && clonedLessons[key].quiz.answers) {
          delete clonedLessons[key].quiz.answers;
        }
      }
      payload.ls = clonedLessons;
      json = JSON.stringify(payload);
    }
    return json;
  }

  /**
   * Commits state to SCORM and localStorage.
   */
  save(scormAdapter) {
    const serialized = this.serialize();

    if (scormAdapter && scormAdapter.initialized) {
      scormAdapter.setSuspendData(serialized);
      if (this.currentLessonId) {
        scormAdapter.setLocation(this.currentLessonId);
      }
      scormAdapter.commit();
    }

    try {
      localStorage.setItem(`neuroclips_state_${this.courseId}`, serialized);
    } catch (e) {}

    this.isDirty = false;
    return true;
  }

  /**
   * Ensures lesson record exists.
   */
  _ensureLesson(lessonId) {
    if (!this.lessons[lessonId]) {
      this.lessons[lessonId] = {
        status: 'incomplete',
        visited: false,
        timeSeconds: 0,
        videoWatchedRatio: 0,
        interactions: {},
        quiz: null
      };
      this.isDirty = true;
    }
    return this.lessons[lessonId];
  }

  markLessonVisited(lessonId, moduleId) {
    this.currentLessonId = lessonId;
    if (moduleId) this.currentModuleId = moduleId;
    const l = this._ensureLesson(lessonId);
    l.visited = true;
    this.isDirty = true;
  }

  updateLessonTime(lessonId, deltaSeconds) {
    const l = this._ensureLesson(lessonId);
    l.timeSeconds = (l.timeSeconds || 0) + deltaSeconds;
    this.isDirty = true;
  }

  updateVideoProgress(lessonId, ratio) {
    const l = this._ensureLesson(lessonId);
    if (ratio > (l.videoWatchedRatio || 0)) {
      l.videoWatchedRatio = Math.min(1.0, Math.round(ratio * 100) / 100);
      this.isDirty = true;
    }
  }

  recordInteraction(lessonId, interactionId, state = { completed: true }) {
    const l = this._ensureLesson(lessonId);
    if (!l.interactions) l.interactions = {};
    l.interactions[interactionId] = state;
    this.isDirty = true;
  }

  recordQuiz(lessonId, score, passed, answers = {}) {
    const l = this._ensureLesson(lessonId);
    const prevAttempts = l.quiz ? l.quiz.attempts || 0 : 0;
    const prevBest = l.quiz ? l.quiz.bestScore || 0 : 0;

    l.quiz = {
      attempts: prevAttempts + 1,
      bestScore: Math.max(prevBest, score),
      passed: Boolean(l.quiz && l.quiz.passed) || passed,
      lastScore: score,
      answers: answers
    };
    this.isDirty = true;
  }

  setLessonStatus(lessonId, status) {
    const l = this._ensureLesson(lessonId);
    l.status = status;
    this.isDirty = true;
  }

  getLessonState(lessonId) {
    return this._ensureLesson(lessonId);
  }

  /**
   * Computes progress across all lessons in course.
   */
  calculateProgress(course) {
    if (!course || !course.modules) return { completed: 0, total: 0, percent: 0 };
    let total = 0;
    let completed = 0;

    for (const mod of course.modules) {
      for (const les of mod.lessons || []) {
        total++;
        const state = this.lessons[les.id];
        if (state && (state.status === 'completed' || state.status === 'passed')) {
          completed++;
        }
      }
    }

    const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { completed, total, percent };
  }
}

window.LearnerStore = LearnerStore;
