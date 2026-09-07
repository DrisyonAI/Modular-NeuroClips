/**
 * NeuroClips SCORM 1.2 & 2004 Standard LMS Communication Adapter
 * Conforms to ADL SCORM specifications with bounded discovery and robust fallbacks.
 */

class ScormAdapter {
  constructor(win = window) {
    this.win = win;
    this.api = null;
    this.version = null; // '1.2' | '2004' | null
    this.initialized = false;
    this.finished = false;
    this.sessionStartTime = Date.now();
  }

  /**
   * Discovers SCORM API by walking window.parent and window.opener up to 8 levels deep.
   */
  findApi(win) {
    let currentWin = win;
    let attempts = 0;
    const maxAttempts = 8;

    while (currentWin && attempts < maxAttempts) {
      // Check SCORM 1.2
      if (currentWin.API) {
        this.version = '1.2';
        return currentWin.API;
      }
      // Check SCORM 2004
      if (currentWin.API_1484_11) {
        this.version = '2004';
        return currentWin.API_1484_11;
      }
      if (currentWin.parent && currentWin.parent !== currentWin) {
        currentWin = currentWin.parent;
      } else {
        break;
      }
      attempts++;
    }

    // Check opener window if opened in popup
    if (win.opener && !win.opener.closed) {
      currentWin = win.opener;
      attempts = 0;
      while (currentWin && attempts < maxAttempts) {
        if (currentWin.API) {
          this.version = '1.2';
          return currentWin.API;
        }
        if (currentWin.API_1484_11) {
          this.version = '2004';
          return currentWin.API_1484_11;
        }
        if (currentWin.parent && currentWin.parent !== currentWin) {
          currentWin = currentWin.parent;
        } else {
          break;
        }
        attempts++;
      }
    }

    return null;
  }

  /**
   * Initializes connection with LMS.
   */
  init() {
    if (this.initialized) return true;

    try {
      this.api = this.findApi(this.win);
      if (!this.api) {
        console.warn('[ScormAdapter] No SCORM LMS API found. Operating in Preview / Standalone mode.');
        return false;
      }

      let res = false;
      if (this.version === '1.2') {
        res = this.api.LMSInitialize('') === 'true';
      } else if (this.version === '2004') {
        res = this.api.Initialize('') === 'true';
      }

      this.initialized = res;
      if (this.initialized) {
        this.sessionStartTime = Date.now();
        console.log(`[ScormAdapter] Successfully initialized SCORM ${this.version} connection.`);
      } else {
        console.error('[ScormAdapter] LMS initialization returned false.', this.error());
      }
      return this.initialized;
    } catch (err) {
      console.error('[ScormAdapter] Exception during LMS initialization:', err);
      return false;
    }
  }

  /**
   * Retrieves value from LMS.
   */
  get(key) {
    if (!this.initialized || !this.api) return '';
    try {
      if (this.version === '1.2') {
        return this.api.LMSGetValue(key) || '';
      } else if (this.version === '2004') {
        return this.api.GetValue(key) || '';
      }
    } catch (err) {
      console.error(`[ScormAdapter] Error getting ${key}:`, err);
    }
    return '';
  }

  /**
   * Sets value in LMS.
   */
  set(key, value) {
    if (!this.initialized || !this.api) return false;
    try {
      const valStr = String(value);
      if (this.version === '1.2') {
        return this.api.LMSSetValue(key, valStr) === 'true';
      } else if (this.version === '2004') {
        return this.api.SetValue(key, valStr) === 'true';
      }
    } catch (err) {
      console.error(`[ScormAdapter] Error setting ${key} = ${value}:`, err);
    }
    return false;
  }

  /**
   * Commits persisted values to LMS database.
   */
  commit() {
    if (!this.initialized || !this.api) return false;
    try {
      if (this.version === '1.2') {
        return this.api.LMSCommit('') === 'true';
      } else if (this.version === '2004') {
        return this.api.Commit('') === 'true';
      }
    } catch (err) {
      console.error('[ScormAdapter] Error during LMSCommit:', err);
    }
    return false;
  }

  /**
   * Closes LMS connection with duration calculation and final commit.
   */
  finish() {
    if (!this.initialized || this.finished || !this.api) return true;
    try {
      this.recordSessionTime();
      this.commit();
      this.finished = true;

      let res = false;
      if (this.version === '1.2') {
        res = this.api.LMSFinish('') === 'true';
      } else if (this.version === '2004') {
        res = this.api.Terminate('') === 'true';
      }
      console.log(`[ScormAdapter] LMS session finished: ${res}`);
      return res;
    } catch (err) {
      console.error('[ScormAdapter] Exception during finish:', err);
      return false;
    }
  }

  /**
   * Helper to set lesson location.
   */
  setLocation(locationId) {
    if (this.version === '1.2') {
      return this.set('cmi.core.lesson_location', locationId);
    } else if (this.version === '2004') {
      return this.set('cmi.location', locationId);
    }
    return false;
  }

  /**
   * Helper to get lesson location.
   */
  getLocation() {
    if (this.version === '1.2') {
      return this.get('cmi.core.lesson_location');
    } else if (this.version === '2004') {
      return this.get('cmi.location');
    }
    return '';
  }

  /**
   * Helper to set course / unit status: 'incomplete', 'completed', 'passed', 'failed'.
   */
  setStatus(status) {
    if (this.version === '1.2') {
      return this.set('cmi.core.lesson_status', status);
    } else if (this.version === '2004') {
      if (status === 'passed' || status === 'failed') {
        this.set('cmi.success_status', status);
        return this.set('cmi.completion_status', 'completed');
      } else {
        return this.set('cmi.completion_status', status);
      }
    }
    return false;
  }

  /**
   * Helper to get status.
   */
  getStatus() {
    if (this.version === '1.2') {
      return this.get('cmi.core.lesson_status');
    } else if (this.version === '2004') {
      const comp = this.get('cmi.completion_status');
      const succ = this.get('cmi.success_status');
      if (succ === 'passed' || succ === 'failed') return succ;
      return comp;
    }
    return '';
  }

  /**
   * Sets numeric score with 0-100 bounds.
   */
  setScore(rawScore, min = 0, max = 100) {
    const raw = Math.round(Number(rawScore));
    if (this.version === '1.2') {
      this.set('cmi.core.score.min', min);
      this.set('cmi.core.score.max', max);
      return this.set('cmi.core.score.raw', raw);
    } else if (this.version === '2004') {
      this.set('cmi.score.min', min);
      this.set('cmi.score.max', max);
      this.set('cmi.score.raw', raw);
      return this.set('cmi.score.scaled', (raw / (max || 100)).toFixed(2));
    }
    return false;
  }

  /**
   * Sets suspend data JSON payload.
   */
  setSuspendData(dataStr) {
    return this.set('cmi.suspend_data', dataStr);
  }

  /**
   * Gets suspend data.
   */
  getSuspendData() {
    return this.get('cmi.suspend_data');
  }

  /**
   * Computes elapsed session time and formats it according to SCORM standard.
   */
  recordSessionTime() {
    const elapsedSeconds = Math.floor((Date.now() - this.sessionStartTime) / 1000);
    if (this.version === '1.2') {
      // Format: HHHH:MM:SS
      const hours = Math.floor(elapsedSeconds / 3600);
      const minutes = Math.floor((elapsedSeconds % 3600) / 60);
      const seconds = elapsedSeconds % 60;
      const fmt = `${String(hours).padStart(4, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
      this.set('cmi.core.session_time', fmt);
    } else if (this.version === '2004') {
      // Format: PT#H#M#S
      const hours = Math.floor(elapsedSeconds / 3600);
      const minutes = Math.floor((elapsedSeconds % 3600) / 60);
      const seconds = elapsedSeconds % 60;
      let fmt = 'PT';
      if (hours > 0) fmt += `${hours}H`;
      if (minutes > 0) fmt += `${minutes}M`;
      fmt += `${seconds}S`;
      this.set('cmi.session_time', fmt);
    }
  }

  /**
   * Retrieves LMS error diagnostics.
   */
  error() {
    if (!this.initialized || !this.api) return null;
    try {
      if (this.version === '1.2') {
        const code = this.api.LMSGetLastError();
        return {
          code,
          text: this.api.LMSGetErrorString(code),
          diagnostic: this.api.LMSGetDiagnostic(code)
        };
      } else if (this.version === '2004') {
        const code = this.api.GetLastError();
        return {
          code,
          text: this.api.GetErrorString(code),
          diagnostic: this.api.GetDiagnostic(code)
        };
      }
    } catch (err) {
      return { code: 'unknown', text: String(err), diagnostic: '' };
    }
    return null;
  }
}

// Attach to window
window.ScormAdapter = ScormAdapter;
