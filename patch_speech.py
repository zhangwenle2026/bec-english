#!/usr/bin/env python3
"""Patch index.html to fix SpeechEngine for mobile compatibility."""

with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_engine_lines = """// SPEECH ENGINE v4.0
// ============================================================
// SPEECH ENGINE v4.0 — mobile-compatible speech with chunking
// Fixes: iOS gesture context, voice preload, cancel+speak race,
//        iOS 15s limit (chunked), Chrome keep-alive, seek gesture
// ============================================================
(function(){
var SE = window.SpeechEngine = {
  rate: 1.0,
  loop: false,

  _words: [],
  _cid: null,
  _wordIdx: 0,
  _playing: false,
  _paused: false,
  _pausedAtIdx: 0,
  _utt: null,
  _timerHandle: null,
  _keepAlive: null,
  _chunkedQueue: null,
  _chunkedIdx: 0,

  // Voice preload
  _voice: null,
  _voiceReady: false,
  _isIOS: /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream,

  _initVoice: function() {
    if (!window.speechSynthesis) return;
    var loadVoices = function() {
      var voices = speechSynthesis.getVoices();
      SE._voice = voices.filter(function(v){ return v.lang === 'en-US' && v.localService; })[0]
        || voices.filter(function(v){ return v.lang && v.lang.indexOf('en') === 0; })[0]
        || voices[0] || null;
      SE._voiceReady = voices.length > 0;
    };
    loadVoices();
    if (typeof speechSynthesis.onvoiceschanged !== 'undefined') {
      speechSynthesis.onvoiceschanged = loadVoices;
    }
  },

  speak: function(containerId, startWordIdx) {
    SE.stop();
    if (!window.speechSynthesis) return;
    var el = document.getElementById(containerId + '-text');
    if (!el) return;
    var fullText = (el.dataset.fulltext || el.textContent).trim();
    SE._words = fullText.split(/\\s+/);
    SE._cid = containerId;
    SE._playing = true;
    SE._paused = false;
    startWordIdx = startWordIdx || 0;
    SE._wordIdx = startWordIdx;

    SE._updateBtn(containerId, true);
    SE._updateRateBtns(containerId);
    SE._speakFrom(startWordIdx);
  },

  _makeUtt: function(text) {
    var utt = new SpeechSynthesisUtterance(text);
    utt.lang = 'en-US';
    utt.rate = SE.rate;
    if (SE._voice) utt.voice = SE._voice;
    return utt;
  },

  _clearKeepAlive: function() {
    if (SE._keepAlive) { clearInterval(SE._keepAlive); SE._keepAlive = null; }
  },

  _speakFrom: function(fromIdx) {
    if (!SE._playing) return;
    speechSynthesis.cancel();
    SE._clearKeepAlive();
    if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
    SE._chunkedQueue = null;

    var textToSpeak = SE._words.slice(fromIdx).join(' ');
    if (!textToSpeak) {
      SE._onFinish();
      return;
    }

    // iOS: chunk long text to avoid 15s silent cutoff
    if (SE._isIOS && textToSpeak.length > 200) {
      setTimeout(function() {
        if (!SE._playing) return;
        SE._speakChunked(textToSpeak, fromIdx);
      }, 50);
      return;
    }

    // Normal path: delay 50ms after cancel() to avoid race condition
    setTimeout(function() {
      if (!SE._playing) return;
      SE._speakDirect(textToSpeak, fromIdx);
    }, 50);
  },

  // Speak without cancel delay (used after drag-seek where cancel already happened)
  _speakFromDirect: function(fromIdx) {
    if (!SE._playing) return;
    SE._clearKeepAlive();
    if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
    SE._chunkedQueue = null;

    var textToSpeak = SE._words.slice(fromIdx).join(' ');
    if (!textToSpeak) {
      SE._onFinish();
      return;
    }

    if (SE._isIOS && textToSpeak.length > 200) {
      SE._speakChunked(textToSpeak, fromIdx);
      return;
    }

    SE._speakDirect(textToSpeak, fromIdx);
  },

  // Core speak logic (no cancel, no delay)
  _speakDirect: function(textToSpeak, fromIdx) {
    var utt = SE._makeUtt(textToSpeak);
    SE._utt = utt;
    SE._wordIdx = fromIdx;

    var wordsInSegment = SE._words.length - fromIdx;
    var boundarySupported = false;

    utt.onboundary = function(e) {
      if (e.name === 'word' && SE._playing && !SE._paused) {
        boundarySupported = true;
        var spoken = textToSpeak.substring(0, e.charIndex);
        var wordCount = spoken ? spoken.trim().split(/\\s+/).length : 0;
        SE._wordIdx = fromIdx + wordCount;
        SE._highlightWord(SE._wordIdx);
        SE._updateProgress(SE._wordIdx / SE._words.length);
      }
    };

    utt.onstart = function() {
      // Chrome keep-alive: pause+resume every 10s to prevent timeout bug
      if (!SE._isIOS) {
        SE._keepAlive = setInterval(function() {
          if (SE._playing && !SE._paused && speechSynthesis.speaking) {
            speechSynthesis.pause();
            speechSynthesis.resume();
          }
        }, 10000);
      }
      // Fallback timer if no boundary events
      if (!boundarySupported) {
        var estMs = (wordsInSegment / 150) * 60000 / SE.rate;
        var msPerWord = estMs / wordsInSegment;
        var startTime = Date.now();
        SE._timerHandle = setInterval(function() {
          if (!SE._playing || SE._paused || boundarySupported) {
            clearInterval(SE._timerHandle); SE._timerHandle = null;
            return;
          }
          var elapsed = Date.now() - startTime;
          var wi = Math.min(fromIdx + Math.floor(elapsed / msPerWord), SE._words.length - 1);
          if (wi !== SE._wordIdx) {
            SE._wordIdx = wi;
            SE._highlightWord(wi);
            SE._updateProgress(wi / SE._words.length);
          }
        }, 100);
      }
    };

    utt.onend = function() {
      SE._clearKeepAlive();
      if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
      if (!SE._playing || SE._paused) return;
      SE._onFinish();
    };

    utt.onerror = function(e) {
      SE._clearKeepAlive();
      if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
      if (e.error === 'canceled' || e.error === 'interrupted') return;
      if (!SE._playing || SE._paused) return;
      SE._onFinish();
    };

    speechSynthesis.speak(utt);
  },

  // iOS chunked playback: split long text into sentences < 200 chars
  _speakChunked: function(text, baseWordIdx) {
    var sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    var queue = [];
    var wordOffset = baseWordIdx;
    sentences.forEach(function(s) {
      var trimmed = s.trim();
      if (!trimmed) return;
      var words = trimmed.split(/\\s+/);
      queue.push({ text: trimmed, startIdx: wordOffset, wordCount: words.length });
      wordOffset += words.length;
    });

    SE._chunkedQueue = queue;
    SE._chunkedIdx = 0;
    SE._playNextChunk();
  },

  _playNextChunk: function() {
    if (!SE._chunkedQueue) return;
    if (SE._chunkedIdx >= SE._chunkedQueue.length || !SE._playing) {
      SE._chunkedQueue = null;
      if (SE._playing && !SE._paused) SE._onFinish();
      return;
    }
    if (SE._paused) return;

    var chunk = SE._chunkedQueue[SE._chunkedIdx];
    var utt = SE._makeUtt(chunk.text);
    SE._utt = utt;

    utt.onboundary = function(e) {
      if (e.name === 'word' && SE._playing && !SE._paused) {
        var spoken = chunk.text.substring(0, e.charIndex);
        var wc = spoken ? spoken.trim().split(/\\s+/).length : 0;
        SE._wordIdx = chunk.startIdx + wc;
        SE._highlightWord(SE._wordIdx);
        SE._updateProgress(SE._wordIdx / SE._words.length);
      }
    };

    utt.onend = function() {
      if (!SE._playing || SE._paused) return;
      SE._chunkedIdx++;
      setTimeout(function() { SE._playNextChunk(); }, 50);
    };

    utt.onerror = function(e) {
      if (e.error === 'canceled' || e.error === 'interrupted') return;
      if (!SE._playing || SE._paused) return;
      SE._chunkedIdx++;
      setTimeout(function() { SE._playNextChunk(); }, 50);
    };

    speechSynthesis.speak(utt);
  },

  _onFinish: function() {
    SE._clearKeepAlive();
    if (SE.loop && SE._cid) {
      SE._wordIdx = 0;
      SE._updateProgress(0);
      SE._clearHighlight();
      setTimeout(function() {
        if (SE._playing && !SE._paused) SE._speakFrom(0);
      }, 400);
    } else {
      SE._playing = false;
      SE._updateBtn(SE._cid, false);
      SE._updateProgress(1);
      SE._clearHighlight();
      SE._utt = null;
    }
  },

  pause: function() {
    if (!SE._playing || SE._paused) return;
    SE._paused = true;
    SE._pausedAtIdx = SE._wordIdx;
    speechSynthesis.cancel();
    SE._clearKeepAlive();
    if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
    SE._updatePauseBtn();
  },

  resume: function() {
    if (!SE._playing || !SE._paused) return;
    SE._paused = false;
    SE._updatePauseBtn();
    // If we were in chunked mode, resume from current chunk
    if (SE._chunkedQueue && SE._chunkedIdx < SE._chunkedQueue.length) {
      SE._playNextChunk();
    } else {
      SE._speakFrom(SE._pausedAtIdx);
    }
  },

  togglePause: function() {
    if (SE._paused) SE.resume(); else SE.pause();
  },

  stop: function() {
    SE._playing = false;
    SE._paused = false;
    speechSynthesis.cancel();
    SE._clearKeepAlive();
    if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
    SE._chunkedQueue = null;
    if (SE._cid) {
      SE._updateBtn(SE._cid, false);
      SE._updateProgress(0);
      SE._clearHighlight();
    }
    SE._cid = null;
    SE._wordIdx = 0;
    SE._words = [];
    SE._utt = null;
  },

  seekTo: function(pct, containerId, skipCancel) {
    var el = document.getElementById(containerId + '-text');
    if (!el) return;
    var allWords = (el.dataset.fulltext || el.textContent).trim().split(/\\s+/);
    var targetIdx = Math.max(0, Math.min(Math.floor(pct * allWords.length), allWords.length - 1));

    if (SE._playing && SE._cid === containerId) {
      if (!skipCancel) {
        speechSynthesis.cancel();
      }
      SE._clearKeepAlive();
      if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
      SE._paused = false;
      SE._wordIdx = targetIdx;
      // Direct speak (no cancel delay) — important for iOS gesture context
      SE._speakFromDirect(targetIdx);
    } else {
      SE.speak(containerId, targetIdx);
    }
  },

  toggleLoop: function(containerId) {
    SE.loop = !SE.loop;
    document.querySelectorAll('.se-loop-btn').forEach(function(btn) {
      btn.classList.toggle('se-loop-active', SE.loop && btn.id === containerId + '-loop-btn');
    });
    if (SE.loop && (!SE._playing || SE._cid !== containerId)) {
      SE.stop();
      SE.speak(containerId, 0);
    }
  },

  setRate: function(r, containerId) {
    SE.rate = r;
    SE._updateRateBtns(containerId);
    if (SE._playing && SE._cid === containerId && !SE._paused) {
      var curIdx = SE._wordIdx;
      speechSynthesis.cancel();
      SE._clearKeepAlive();
      if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
      SE._speakFrom(curIdx);
    }
  },

  _togglePlay: function(containerId) {
    if (SE._playing && SE._cid === containerId) {
      SE.loop = false;
      document.querySelectorAll('.se-loop-btn').forEach(function(b){ b.classList.remove('se-loop-active'); });
      SE.stop();
    } else {
      SE.stop();
      SE.speak(containerId, 0);
    }
  },

  // ---- UI ----
  _highlightWord: function(idx) {
    if (!SE._cid) return;
    var container = document.getElementById(SE._cid + '-text');
    if (!container) return;
    container.querySelectorAll('.se-word').forEach(function(s, i) {
      s.classList.toggle('se-word-active', i === idx);
    });
  },

  _clearHighlight: function() {
    if (!SE._cid) return;
    var container = document.getElementById(SE._cid + '-text');
    if (!container) return;
    container.querySelectorAll('.se-word').forEach(function(s){ s.classList.remove('se-word-active'); });
  },

  _updateProgress: function(pct) {
    if (!SE._cid) return;
    var fill = document.getElementById(SE._cid + '-prog-fill');
    var thumb = document.getElementById(SE._cid + '-prog-thumb');
    var pct100 = Math.round(Math.min(1, Math.max(0, pct)) * 100);
    if (fill) fill.style.width = pct100 + '%';
    if (thumb) thumb.style.left = pct100 + '%';
  },

  _updateBtn: function(cid, playing) {
    var btn = document.getElementById(cid + '-play-btn');
    if (!btn) return;
    btn.textContent = playing ? '\\u23f9 \\u505c\\u6b62' : '\\ud83d\\udd08 \\u6717\\u8bfb';
    btn.classList.toggle('se-playing', playing);
    SE._updatePauseBtn();
  },

  _updatePauseBtn: function() {
    if (!SE._cid) return;
    var btn = document.getElementById(SE._cid + '-pause-btn');
    if (!btn) return;
    btn.textContent = SE._paused ? '\\u25b6' : '\\u23f8';
    btn.style.display = SE._playing ? 'inline-block' : 'none';
  },

  _updateRateBtns: function(cid) {
    if (!cid) return;
    [0.6, 1.0, 1.3].forEach(function(r) {
      var btn = document.getElementById(cid + '-rate-' + r.toString().replace('.',''));
      if (btn) btn.classList.toggle('se-rate-active', SE.rate === r);
    });
  },

  // ---- DOM builders ----
  buildWordSpans: function(text, containerId) {
    var words = text.trim().split(/\\s+/);
    return '<span id="' + containerId + '-text" class="se-text-wrap" data-fulltext="' + text.replace(/"/g,'&quot;') + '">' +
      words.map(function(w) {
        return '<span class="se-word">' + w.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
      }).join(' ') + '</span>';
  },

  buildPlayer: function(containerId) {
    return '<div class="se-player" id="' + containerId + '-player">' +
      '<button id="' + containerId + '-play-btn" class="se-play-btn" onclick="SpeechEngine._togglePlay(\\'' + containerId + '\\')">' + '\\ud83d\\udd08 \\u6717\\u8bfb' + '</button>' +
      '<button id="' + containerId + '-pause-btn" class="se-rate-btn" style="display:none;font-size:13px;padding:4px 10px" onclick="SpeechEngine.togglePause()">' + '\\u23f8' + '</button>' +
      '<button id="' + containerId + '-loop-btn" class="se-loop-btn se-rate-btn" title="\\u5faa\\u73af" onclick="SpeechEngine.toggleLoop(\\'' + containerId + '\\')">' + '\\ud83d\\udd01' + '</button>' +
      '<span class="se-rate-group">' +
        '<button id="' + containerId + '-rate-06" class="se-rate-btn" onclick="SpeechEngine.setRate(0.6,\\'' + containerId + '\\')">' + '\\u6162' + '</button>' +
        '<button id="' + containerId + '-rate-10" class="se-rate-btn se-rate-active" onclick="SpeechEngine.setRate(1.0,\\'' + containerId + '\\')">' + '\\u6b63\\u5e38' + '</button>' +
        '<button id="' + containerId + '-rate-13" class="se-rate-btn" onclick="SpeechEngine.setRate(1.3,\\'' + containerId + '\\')">' + '\\u5feb' + '</button>' +
      '</span>' +
      '<div class="se-progress-wrap" id="' + containerId + '-prog">' +
        '<div class="se-progress-fill" id="' + containerId + '-prog-fill"></div>' +
        '<div class="se-progress-thumb" id="' + containerId + '-prog-thumb"' +
        ' onmousedown="SpeechEngine._startDrag(event,\\'' + containerId + '\\')"' +
        ' ontouchstart="SpeechEngine._startDrag(event,\\'' + containerId + '\\')">' + '</div>' +
      '</div>' +
    '</div>';
  },

  _startDrag: function(e, containerId) {
    e.preventDefault(); e.stopPropagation();
    var bar = document.getElementById(containerId + '-prog');
    if (!bar) return;

    var wasPlaying = SE._playing && SE._cid === containerId;
    if (wasPlaying) {
      speechSynthesis.cancel();
      SE._clearKeepAlive();
      if (SE._timerHandle) { clearInterval(SE._timerHandle); SE._timerHandle = null; }
      SE._paused = true;
    }

    function getPct(clientX) {
      var rect = bar.getBoundingClientRect();
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    }

    function move(ev) {
      var cx = ev.touches ? ev.touches[0].clientX : ev.clientX;
      var pct = getPct(cx);
      var fill = document.getElementById(containerId + '-prog-fill');
      var thumb = document.getElementById(containerId + '-prog-thumb');
      if (fill) fill.style.width = Math.round(pct*100) + '%';
      if (thumb) thumb.style.left = Math.round(pct*100) + '%';
      var el = document.getElementById(containerId + '-text');
      if (el) {
        var ws = (el.dataset.fulltext || el.textContent).trim().split(/\\s+/);
        var wi = Math.min(Math.floor(pct * ws.length), ws.length - 1);
        el.querySelectorAll('.se-word').forEach(function(s,i){ s.classList.toggle('se-word-active', i === wi); });
      }
    }

    function up(ev) {
      var cx = ev.changedTouches ? ev.changedTouches[0].clientX : ev.clientX;
      var pct = getPct(cx);
      SE._paused = false;
      // skipCancel=true: cancel already done at drag start, preserve iOS gesture context
      SE.seekTo(pct, containerId, true);
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.removeEventListener('touchmove', move);
      document.removeEventListener('touchend', up);
    }

    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
    document.addEventListener('touchmove', move, {passive:false});
    document.addEventListener('touchend', up);
  }
};

// Init voice preload
SE._initVoice();

// Styles
var style = document.createElement('style');
style.textContent = [
  '.se-word{display:inline;transition:background 0.15s;border-radius:3px;padding:0 1px}',
  '.se-word-active{background:#ffe066;color:#1a1a2e;font-weight:700;box-shadow:0 1px 6px rgba(255,200,0,0.3);padding:0 2px;border-radius:4px}',
  '.se-player{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:12px;padding:8px 10px;background:rgba(0,0,0,0.04);border-radius:10px}',
  '.se-play-btn{background:linear-gradient(135deg,#ff4b4b,#ff8c42);color:#fff;border:none;border-radius:16px;padding:5px 14px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;flex-shrink:0}',
  '.se-play-btn.se-playing{background:linear-gradient(135deg,#555,#333)}',
  '.se-loop-btn{font-size:14px!important;padding:4px 9px!important;line-height:1}',
  '.se-loop-active{background:linear-gradient(135deg,#22c55e,#16a34a)!important;color:#fff!important;box-shadow:0 0 8px rgba(34,197,94,0.5)!important}',
  '.se-rate-group{display:flex;gap:3px;flex-shrink:0}',
  '.se-rate-btn{background:rgba(0,0,0,0.07);border:none;border-radius:10px;padding:4px 8px;font-size:11px;font-weight:700;color:#555;cursor:pointer;flex-shrink:0}',
  '.se-rate-btn.se-rate-active{background:linear-gradient(135deg,#ff4b4b,#ff8c42);color:#fff}',
  '.se-progress-wrap{flex:1;min-width:80px;height:8px;background:rgba(0,0,0,0.1);border-radius:8px;position:relative;touch-action:none}',
  '.se-progress-fill{height:100%;background:linear-gradient(90deg,#ff4b4b,#ff8c42);border-radius:8px;width:0%;pointer-events:none}',
  '.se-progress-thumb{position:absolute;top:50%;left:0%;transform:translate(-50%,-50%);width:18px;height:18px;background:#fff;border:2.5px solid #ff4b4b;border-radius:50%;cursor:grab;box-shadow:0 1px 5px rgba(0,0,0,0.25)}',
  '.se-progress-thumb:active{cursor:grabbing;transform:translate(-50%,-50%) scale(1.25)}',
  '.se-text-wrap{line-height:2;display:inline}'
].join('\\n');
document.head.appendChild(style);

})();
""".split('\n')

new_speak_lines = """function speak(text, btn) {
  // For single words/short phrases
  SpeechEngine.stop();
  if (!window.speechSynthesis) return;
  // Delay 50ms after stop()'s cancel() to avoid race condition
  setTimeout(function() {
    var u = new SpeechSynthesisUtterance(text);
    u.lang = 'en-US'; u.rate = SpeechEngine.rate;
    if (SpeechEngine._voice) u.voice = SpeechEngine._voice;
    speechSynthesis.speak(u);
  }, 50);
  if (btn) { btn.style.transform='scale(1.3)'; setTimeout(function(){btn.style.transform='';},300); }
}
""".split('\n')

# Find exact line ranges
engine_start = None
engine_end = None
speak_start = None
speak_end = None

for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == '// SPEECH ENGINE v3.2' and engine_start is None:
        engine_start = i
    if stripped == '})();' and engine_start is not None and engine_end is None:
        engine_end = i
    if 'function speak(text, btn)' in stripped and speak_start is None:
        speak_start = i
    if speak_start is not None and speak_end is None and stripped == '}' and i > speak_start + 2:
        if i - speak_start < 15:
            speak_end = i

print(f"Engine: lines {engine_start+1}-{engine_end+1}")
print(f"speak(): lines {speak_start+1}-{speak_end+1}")

assert engine_start is not None
assert engine_end is not None
assert speak_start is not None
assert speak_end is not None
assert engine_end < speak_start

# Build output
new_lines = []
new_lines.extend(lines[:engine_start])
for l in new_engine_lines:
    new_lines.append(l + '\n')
new_lines.extend(lines[engine_end+1:speak_start])
for l in new_speak_lines:
    new_lines.append(l + '\n')
new_lines.extend(lines[speak_end+1:])

with open('index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Done. New file has {len(new_lines)} lines (was {len(lines)})")
