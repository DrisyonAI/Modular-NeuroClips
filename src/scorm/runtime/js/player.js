/**
 * NeuroClips Master SCORM Player Application
 * Data-driven single-page learner application with continuous course navigation,
 * progress tracking, SCORM 1.2/2004 sync, and UI matching reference screenshots 59-65.
 */

class NeuroClipsPlayer {
  constructor() {
    this.scorm = new ScormAdapter(window);
    this.store = null;
    this.course = null;
    this.currentModule = null;
    this.currentLesson = null;
    this.currentView = 'home'; // 'home' | 'lesson' | 'completion'
    this.autosaveTimer = null;
    this.videoElement = null;
  }

  /**
   * Initializes player on page load.
   */
  async init() {
    console.log('[NeuroClipsPlayer] Initializing...');

    // 1. Initialize SCORM connection
    const scormConnected = this.scorm.init();
    if (!scormConnected) {
      const banner = document.getElementById('preview-mode-banner');
      if (banner) banner.classList.remove('hidden');
    }

    // 2. Load Course JSON
    try {
      this.course = await this.loadCourseData();
    } catch (err) {
      console.error('[NeuroClipsPlayer] Failed to load course data:', err);
      document.getElementById('app').innerHTML = `
        <div style="padding: 40px; text-align: center; color: #DC2626;">
          <h2>Error Loading Course</h2>
          <p>${err.message}</p>
        </div>
      `;
      return;
    }

    // 3. Initialize Store
    const courseId = this.course.course.id || 'course-001';
    this.store = new LearnerStore(courseId);
    const restored = this.store.load(this.scorm);

    // Initial SCORM status if not attempted
    const currentStatus = this.scorm.getStatus();
    if (!currentStatus || currentStatus === 'not attempted') {
      this.scorm.setStatus('incomplete');
      this.scorm.commit();
    }

    // 4. Setup Global Teardown & Autosave
    this.setupLifecycleEvents();
    this.startAutosave();

    // 5. Render Header
    this.renderHeader();

    // 6. Check Resume Prompt
    const savedLocation = this.scorm.getLocation() || this.store.currentLessonId;
    const showResume = this.course.course.settings?.showResumePrompt !== false;

    if (restored && savedLocation && showResume && this.findLesson(savedLocation)) {
      this.showResumeModal(savedLocation);
    } else {
      this.navigateHome();
    }
  }

  /**
   * Loads course data from data/course.json with fallback to window.COURSE_DATA.
   */
  async loadCourseData() {
    if (window.COURSE_DATA) {
      return window.COURSE_DATA;
    }
    const res = await fetch('data/course.json');
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} while fetching data/course.json`);
    }
    return await res.json();
  }

  /**
   * Sets up window beforeunload & pagehide handlers.
   */
  setupLifecycleEvents() {
    const handleExit = () => {
      if (this.store) {
        this.store.save(this.scorm);
      }
      if (this.scorm) {
        this.scorm.finish();
      }
    };

    window.addEventListener('beforeunload', handleExit);
    window.addEventListener('pagehide', handleExit);
  }

  /**
   * Autosave interval.
   */
  startAutosave() {
    const intervalSec = this.course?.course?.settings?.autosaveSeconds || 10;
    this.autosaveTimer = setInterval(() => {
      if (this.store && this.store.isDirty) {
        this.store.save(this.scorm);
      }
    }, intervalSec * 1000);
  }

  /**
   * Finds a lesson by ID across all modules.
   */
  findLesson(lessonId) {
    if (!this.course || !this.course.course.modules) return null;
    for (const mod of this.course.course.modules) {
      for (const les of mod.lessons || []) {
        if (les.id === lessonId) {
          return { module: mod, lesson: les };
        }
      }
    }
    return null;
  }

  /**
   * Renders the persistent App Header (Matches Screenshots 63-65).
   */
  renderHeader() {
    const headerEl = document.getElementById('app-header');
    if (!headerEl) return;

    const c = this.course.course;
    const currentMod = this.currentModule || (c.modules && c.modules[0]) || { number: 1, title: c.title };
    const modNumber = (currentMod.number !== undefined && currentMod.number !== null && currentMod.number !== '') ? currentMod.number : 1;
    const rawModTitle = currentMod.title || currentMod.name || c.title || `Module ${modNumber}`;
    let cleanModTitle = rawModTitle;
    const modPrefixRegex = new RegExp(`^Module\\s*${modNumber}\\s*:\\s*`, 'i');
    if (modPrefixRegex.test(cleanModTitle)) {
      cleanModTitle = cleanModTitle.replace(modPrefixRegex, '').trim();
    }

    headerEl.innerHTML = `
      <div class="header-left">
        <span class="module-badge">Module ${modNumber}</span>
        <span class="module-header-title">${esc(cleanModTitle)}</span>
      </div>
      <div class="header-right">
        <button type="button" class="dropdown-trigger-btn" onclick="player.toggleLessonsDropdown()">
          <span>Lessons</span>
          <span style="font-size: 10px;">▼</span>
        </button>
        <div id="lessons-dropdown-menu" class="dropdown-menu"></div>
      </div>
    `;

    this.populateLessonsDropdown();
  }

  /**
   * Toggles dropdown menu visibility.
   */
  toggleLessonsDropdown() {
    const menu = document.getElementById('lessons-dropdown-menu');
    if (menu) {
      menu.classList.toggle('active');
    }
  }

  /**
   * Populates items inside the "Lessons ˅" dropdown.
   */
  populateLessonsDropdown() {
    const menu = document.getElementById('lessons-dropdown-menu');
    if (!menu || !this.course) return;

    let itemsHtml = '';
    for (const mod of this.course.course.modules || []) {
      const mNum = (mod.number !== undefined && mod.number !== null && mod.number !== '') ? mod.number : 1;
      for (const les of mod.lessons || []) {
        const state = this.store ? this.store.getLessonState(les.id) : null;
        const isCurrent = this.currentLesson && this.currentLesson.id === les.id;
        const isDone = state && (state.status === 'completed' || state.status === 'passed');
        const lNum = les.number || `${mNum}.1`;
        const lTitle = les.title || les.name || `Lesson ${lNum}`;

        let statusIcon = '⚪';
        if (isDone) statusIcon = '✅';
        else if (isCurrent) statusIcon = '🔴';
        else if (state && state.visited) statusIcon = '🔵';

        itemsHtml += `
          <div class="dropdown-item ${isCurrent ? 'active' : ''}" onclick="player.selectLessonFromDropdown('${les.id}')">
            <span class="dropdown-status-icon">${statusIcon}</span>
            <div>
              <div style="font-size: 11px; color: #64748B;">${lNum}</div>
              <div>${esc(lTitle)}</div>
            </div>
          </div>
        `;
      }
    }

    menu.innerHTML = itemsHtml;
  }

  selectLessonFromDropdown(lessonId) {
    this.toggleLessonsDropdown();
    this.navigateLesson(lessonId);
  }

  /**
   * Resume Modal Dialog.
   */
  showResumeModal(lessonId) {
    const modalEl = document.getElementById('app-modal');
    if (!modalEl) {
      this.navigateLesson(lessonId);
      return;
    }

    const match = this.findLesson(lessonId);
    const lessonTitle = match ? match.lesson.title : 'your previous lesson';

    modalEl.innerHTML = `
      <div class="modal-overlay">
        <div class="modal-card">
          <h3 class="modal-title">Resume Course</h3>
          <p class="modal-desc">Would you like to resume where you left off?<br><strong>${esc(lessonTitle)}</strong></p>
          <div class="modal-actions">
            <button type="button" class="btn-secondary" onclick="player.dismissResume(false)">Start from Beginning</button>
            <button type="button" class="btn-primary" onclick="player.dismissResume(true, '${lessonId}')">Resume</button>
          </div>
        </div>
      </div>
    `;
    modalEl.style.display = 'block';
  }

  dismissResume(resume, lessonId) {
    const modalEl = document.getElementById('app-modal');
    if (modalEl) modalEl.style.display = 'none';

    if (resume && lessonId) {
      this.navigateLesson(lessonId);
    } else {
      this.navigateHome();
    }
  }

  /**
   * Navigation: Course Home / Overview Screen.
   */
  navigateHome() {
    this.currentView = 'home';
    this.currentLesson = null;
    this.renderHeader();

    const container = document.getElementById('app-content');
    if (!container) return;

    const c = this.course.course;
    const firstMod = (c.modules && c.modules[0]) || {};
    const firstModNum = (firstMod.number !== undefined && firstMod.number !== null && firstMod.number !== '') ? firstMod.number : 1;
    const firstLesson = firstMod.lessons?.[0];
    const firstLessonId = firstLesson?.id;
    const progress = this.store.calculateProgress(c);

    // Hero background / artwork
    const heroTitle = c.title || 'AI Powered HR';
    const firstLessonNum = firstLesson?.number || `${firstModNum}.1`;
    const introVideo = c.introBackgroundVideo || c.intro?.background_video || c.intro_video;

    let modulesHtml = '';
    for (const mod of c.modules || []) {
      const mNum = (mod.number !== undefined && mod.number !== null && mod.number !== '') ? mod.number : 1;
      const mTitle = mod.title || mod.name || `Module ${mNum}`;
      modulesHtml += `
        <div class="module-card">
          <div class="module-card-header">
            <div class="module-card-title-group">
              <span class="module-number-pill">Module ${mNum}</span>
              <span class="module-card-title">${esc(mTitle)}</span>
            </div>
            <div style="font-size: 12px; color: #64748B;">${mod.durationMinutes ? `${mod.durationMinutes} min` : ''}</div>
          </div>
          <div class="module-lessons-list">
            ${(mod.lessons || []).map(les => {
              const state = this.store.getLessonState(les.id);
              const isDone = state && (state.status === 'completed' || state.status === 'passed');
              const lNum = les.number || `${mNum}.1`;
              const lTitle = les.title || les.name || `Lesson ${lNum}`;
              return `
                <div class="lesson-row-card" onclick="player.navigateLesson('${les.id}')">
                  <div class="lesson-row-left">
                    <span class="lesson-row-num">${lNum}</span>
                    <span class="lesson-row-title">${esc(lTitle)}</span>
                  </div>
                  <div class="lesson-row-right">
                    ${les.durationMinutes ? `<span class="lesson-badge">${les.durationMinutes}</span>` : ''}
                    <span class="lesson-status-badge">${isDone ? '✅' : '⚪'}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    container.innerHTML = `
      <!-- Hero Card - Matches Screenshots 63-65 & Reference Background Video -->
      <div class="hero-card">
        ${introVideo ? `
          <div class="hero-video-wrapper">
            <video class="hero-bg-video" autoplay muted loop playsinline preload="auto">
              <source src="${esc(introVideo)}" type="video/mp4" />
            </video>
            <div class="hero-video-overlay"></div>
          </div>
        ` : `
          <div class="hero-art-container">
            <div style="width: 320px; height: 220px; background: radial-gradient(circle, rgba(229,37,42,0.15) 0%, rgba(30,27,75,0.05) 70%); border-radius: 50%;"></div>
          </div>
        `}
        <div class="hero-content-overlay">
          <h1 class="hero-title">${esc(heroTitle)}</h1>
          ${firstLessonId ? `
            <button type="button" class="hero-start-btn" onclick="player.navigateLesson('${firstLessonId}')">
              <span>Start Lesson ${firstLessonNum}</span>
              <span class="hero-btn-arrow">→</span>
            </button>
          ` : ''}
        </div>
      </div>

      <!-- Course Overview Card -->
      <div class="course-overview-card">
        <div class="course-progress-header">
          <span class="progress-label">Course Progress</span>
          <span class="progress-pct">${progress.percent}%</span>
        </div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill" style="width: ${progress.percent}%;"></div>
        </div>

        <div class="meta-grid">
          ${c.audience ? `
            <div class="meta-item">
              <div class="meta-item-label">Target Audience</div>
              <div class="meta-item-value">${esc(c.audience)}</div>
            </div>
          ` : ''}
          ${c.durationMinutes ? `
            <div class="meta-item">
              <div class="meta-item-label">Total Duration</div>
              <div class="meta-item-value">${c.durationMinutes} Minutes</div>
            </div>
          ` : ''}
          <div class="meta-item">
            <div class="meta-item-label">Curriculum Scope</div>
            <div class="meta-item-value">${c.modules?.length || 0} Modules • ${progress.total} Lessons</div>
          </div>
        </div>

        ${c.description ? `<p style="font-size: 14px; color: #475569; margin-bottom: 20px; line-height: 1.6;">${esc(c.description)}</p>` : ''}

        ${(c.learningObjectives || []).length > 0 ? `
          <div class="learning-objectives-box">
            <div class="objectives-title">Learning Objectives</div>
            <ul class="objectives-list">
              ${c.learningObjectives.map(obj => `
                <li class="objective-item">
                  <span class="objective-check">✓</span>
                  <span>${esc(obj)}</span>
                </li>
              `).join('')}
            </ul>
          </div>
        ` : ''}
      </div>

      <!-- Modules Accordion -->
      <div class="modules-accordion">
        ${modulesHtml}
      </div>
    `;

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /**
   * Navigation: Lesson Player Screen (Matches Screenshots 59-62).
   */
  navigateLesson(lessonId) {
    const match = this.findLesson(lessonId);
    if (!match) return;

    this.currentView = 'lesson';
    this.currentModule = match.module;
    this.currentLesson = match.lesson;

    // Update store and SCORM
    this.store.markLessonVisited(lessonId, match.module.id);
    this.scorm.setLocation(lessonId);
    this.scorm.commit();

    this.renderHeader();
    this.populateLessonsDropdown();

    const container = document.getElementById('app-content');
    if (!container) return;

    const les = match.lesson;
    const mod = match.module;
    const mNum = (mod.number !== undefined && mod.number !== null && mod.number !== '') ? mod.number : 1;
    const lNum = les.number || `${mNum}.1`;
    const cleanLName = (les.title || les.name || '').replace(new RegExp(`^(Lesson\\s*)?${lNum}\\s*[:\\-]?\\s*`, 'i'), '').trim() || les.title || les.name || `Lesson ${lNum}`;
    const lDisplayTitle = (les.title && (les.title.startsWith(`${lNum} `) || les.title.startsWith(`Lesson ${lNum}`))) ? les.title : `${lNum} ${cleanLName}`;
    const lesState = this.store.getLessonState(lessonId);

    // Calculate previous and next lesson links
    const flatLessons = [];
    for (const m of this.course.course.modules || []) {
      for (const l of m.lessons || []) {
        flatLessons.push(l);
      }
    }
    const currentIndex = flatLessons.findIndex(l => l.id === lessonId || l === lessonId);
    const prevLesson = currentIndex > 0 ? flatLessons[currentIndex - 1] : null;
    const nextLesson = currentIndex < flatLessons.length - 1 ? flatLessons[currentIndex + 1] : null;

    // Content blocks HTML
    let contentHtml = '';
    for (const block of les.content || []) {
      contentHtml += renderBlock(block);
    }
    for (const inter of les.interactions || []) {
      contentHtml += renderBlock(inter);
    }

    container.innerHTML = `
      <!-- Back Navigation Row (Screenshot 62) -->
      <div class="nav-back-row">
        <a class="back-link" onclick="player.navigateHome()">← Back to Home</a>
        <button type="button" class="dropdown-trigger-btn" style="background: #FFFFFF; color: var(--color-navy); border-color: var(--color-border);" onclick="player.toggleLessonsDropdown()">
          <span>Lessons</span>
          <span style="font-size: 10px;">▼</span>
        </button>
      </div>

      <!-- Main Lesson Card (Screenshot 62) -->
      <div class="lesson-card">
        <!-- Eyebrow -->
        <div class="lesson-eyebrow">LESSON ${lNum}</div>

        <!-- Main Title -->
        <h1 class="lesson-title">${esc(lDisplayTitle)}</h1>

        <!-- Badges Row (Duration & Learning Mode) -->
        <div class="lesson-badges-row">
          ${les.durationMinutes ? `<span class="info-pill">Duration: ${les.durationMinutes}</span>` : ''}
          ${les.learningMode ? `<span class="info-pill">Learning Mode: ${esc(les.learningMode)}</span>` : ''}
        </div>

        <!-- Target Audience Line -->
        ${(les.targetAudience || this.course.course.audience) ? `
          <div class="lesson-audience-line">
            <span class="lesson-audience-label">Target Audience:</span>
            <span>${esc(les.targetAudience || this.course.course.audience)}</span>
          </div>
        ` : ''}

        <!-- Video Block (Screenshot 59) -->
        ${les.video && les.video.src ? `
          <div class="video-block-container">
            <video id="lesson-video" class="lesson-video-player" controls preload="metadata" ${les.video.poster ? `poster="${esc(les.video.poster)}"` : ''}>
              <source src="${esc(les.video.src)}" type="video/mp4" />
              ${les.video.captions ? `<track src="${esc(les.video.captions)}" kind="subtitles" srclang="en" label="English" default />` : ''}
              Your browser does not support HTML5 video.
            </video>
            <div class="video-caption-bar">
              <span class="video-play-icon">▶</span>
              <span>Lesson ${lNum} Video Lesson</span>
            </div>
          </div>
        ` : ''}

        <!-- Content Blocks Section (Screenshots 59-62) -->
        <div class="content-section">
          ${contentHtml}
        </div>

        <!-- Quiz / Assessment Section -->
        <div id="lesson-quiz-mount"></div>
      </div>

      <!-- Bottom Navigation Footer (Screenshot 61) -->
      <div class="lesson-nav-footer">
        <button type="button" class="nav-btn-prev" ${prevLesson ? `onclick="player.navigateLesson('${prevLesson.id}')"` : 'disabled'}>
          ← Previous
        </button>
        <button type="button" class="nav-btn-next" onclick="player.onNextClicked('${nextLesson ? nextLesson.id : 'COMPLETION'}')">
          <span>${nextLesson ? 'Next' : 'Complete Course'}</span>
          <span>→</span>
        </button>
      </div>
    `;

    // Initialize Video Player Tracking
    if (les.video && les.video.src) {
      this.initVideoTracking(les);
    }

    // Initialize Quiz Engine
    if (les.quiz && les.quiz.questions && les.quiz.questions.length > 0) {
      const quizMount = document.getElementById('lesson-quiz-mount');
      const quizEngine = new QuizEngine(les.quiz, (score, passed, answers) => {
        this.onQuizCompleted(les, score, passed, answers);
      });
      window.setActiveQuizInstance(quizEngine);
      quizEngine.render(quizMount, lesState ? lesState.quiz : null);
    }

    // Handle view-based completion
    if (!les.completion || les.completion.type === 'view') {
      this.evaluateLessonCompletion(les, 'view');
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /**
   * Tracks video playback and completion ratio.
   */
  initVideoTracking(lesson) {
    this.videoElement = document.getElementById('lesson-video');
    if (!this.videoElement) return;

    const threshold = lesson.video?.completionThreshold || 0.9;

    this.videoElement.addEventListener('timeupdate', () => {
      if (this.videoElement.duration > 0) {
        const ratio = this.videoElement.currentTime / this.videoElement.duration;
        this.store.updateVideoProgress(lesson.id, ratio);

        if (ratio >= threshold) {
          this.evaluateLessonCompletion(lesson, 'video');
        }
      }
    });

    this.videoElement.addEventListener('ended', () => {
      this.store.updateVideoProgress(lesson.id, 1.0);
      this.evaluateLessonCompletion(lesson, 'video');
    });
  }

  /**
   * Quiz completion handler.
   */
  onQuizCompleted(lesson, score, passed, answers) {
    this.store.recordQuiz(lesson.id, score, passed, answers);
    this.scorm.setScore(score);

    const requiredScore = lesson.completion?.requiredScore || lesson.quiz?.passingScore || 70;
    if (passed || score >= requiredScore) {
      this.evaluateLessonCompletion(lesson, 'quiz_pass');
    } else {
      this.evaluateLessonCompletion(lesson, 'quiz');
    }

    this.store.save(this.scorm);
    this.populateLessonsDropdown();
  }

  /**
   * Evaluates completion rules for a lesson.
   */
  evaluateLessonCompletion(lesson, eventType) {
    const compRule = lesson.completion?.type || (lesson.quiz ? 'quiz_pass' : (lesson.video ? 'video' : 'view'));
    let isComplete = false;
    const state = this.store.getLessonState(lesson.id);

    if (compRule === 'view') {
      isComplete = true;
    } else if (compRule === 'video') {
      isComplete = (state.videoWatchedRatio || 0) >= (lesson.video?.completionThreshold || 0.9);
    } else if (compRule === 'quiz') {
      isComplete = state.quiz && state.quiz.attempts > 0;
    } else if (compRule === 'quiz_pass') {
      isComplete = state.quiz && state.quiz.passed;
    } else if (compRule === 'all_required_components') {
      const videoOk = !lesson.video?.required || ((state.videoWatchedRatio || 0) >= (lesson.video?.completionThreshold || 0.9));
      const quizOk = !lesson.quiz || (state.quiz && state.quiz.passed);
      isComplete = videoOk && quizOk;
    }

    if (isComplete) {
      this.store.setLessonStatus(lesson.id, 'completed');
      this.store.save(this.scorm);
      this.evaluateOverallCourseCompletion();
    }
  }

  /**
   * Evaluates if entire course has met completion requirements.
   */
  evaluateOverallCourseCompletion() {
    const progress = this.store.calculateProgress(this.course.course);
    if (progress.completed >= progress.total && progress.total > 0) {
      // Find highest score if any quizzes
      let bestScore = 0;
      let hasScores = false;
      for (const lId of Object.keys(this.store.lessons)) {
        if (this.store.lessons[lId]?.quiz) {
          hasScores = true;
          bestScore = Math.max(bestScore, this.store.lessons[lId].quiz.bestScore || 0);
        }
      }

      if (hasScores) {
        this.scorm.setScore(bestScore);
        this.scorm.setStatus('passed');
      } else {
        this.scorm.setStatus('completed');
      }
      this.scorm.commit();
      console.log('[NeuroClipsPlayer] Course fully completed and committed to LMS.');
    }
  }

  onNextClicked(target) {
    if (target === 'COMPLETION') {
      this.navigateCompletion();
    } else {
      this.navigateLesson(target);
    }
  }

  /**
   * Screen 4: Course Completion View.
   */
  navigateCompletion() {
    this.currentView = 'completion';
    this.currentLesson = null;
    this.evaluateOverallCourseCompletion();
    this.renderHeader();

    const container = document.getElementById('app-content');
    if (!container) return;

    const progress = this.store.calculateProgress(this.course.course);
    const lmsStatus = this.scorm.getStatus() || 'completed';

    container.innerHTML = `
      <div class="completion-card">
        <div class="completion-icon">🏆</div>
        <h2 class="completion-title">Course Completed!</h2>
        <p class="completion-text">
          Congratulations! You have completed all <strong>${progress.total} lessons</strong> in <em>${esc(this.course.course.title)}</em>.
          Your progress and final gradebook have been committed to the Learning Management System.
        </p>

        <div style="margin: 20px 0; padding: 14px; background: #F8FAFC; border-radius: 12px; display: inline-block; font-size: 13px;">
          <span>LMS Status: <strong>${esc(lmsStatus.toUpperCase())}</strong></span>
          <span style="margin: 0 8px; color: #CBD5E1;">•</span>
          <span>Score: <strong>${this.scorm.get('cmi.core.score.raw') || 100}%</strong></span>
        </div>

        <div class="completion-actions">
          <button type="button" class="btn-secondary" onclick="player.navigateHome()">Return to Course Home</button>
          <button type="button" class="btn-primary" onclick="player.navigateLesson('${this.course.course.modules?.[0]?.lessons?.[0]?.id}')">Review from Beginning</button>
        </div>
      </div>
    `;

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// Instantiate global player
const player = new NeuroClipsPlayer();
window.player = player;

window.addEventListener('DOMContentLoaded', () => {
  player.init();
});
