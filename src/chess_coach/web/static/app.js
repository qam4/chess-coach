/* Chess Coach — main application script */

(function () {
  'use strict';

  // --- DOM elements ---
  var fenInput = document.getElementById('fenInput');
  var depthSlider = document.getElementById('depthSlider');
  var depthValue = document.getElementById('depthValue');
  var levelSelect = document.getElementById('levelSelect');
  var analyzeBtn = document.getElementById('analyzeBtn');
  var coachingText = document.getElementById('coachingText');
  var coachingMeta = document.getElementById('coachingMeta');
  var userFeedback = document.getElementById('userFeedback');
  var spinner = document.getElementById('spinner');
  var evalFill = document.getElementById('evalFill');
  var arrowSvg = document.getElementById('arrowSvg');
  var analyzeControls = document.getElementById('analyzeControls');
  var playControls = document.getElementById('playControls');
  var moveListPanel = document.getElementById('moveListPanel');
  var hintContainer = document.getElementById('hintContainer');
  var hintBtn = document.getElementById('hintBtn');
  var hintText = document.getElementById('hintText');
  var moveList = document.getElementById('moveList');
  var gameResult = document.getElementById('gameResult');
  var newGameBtn = document.getElementById('newGameBtn');
  var undoBtn = document.getElementById('undoBtn');
  var colorModal = document.getElementById('colorModal');
  var debugContent = document.getElementById('debugContent');
  var strengthSlider = document.getElementById('strengthSlider');
  var strengthLabel = document.getElementById('strengthLabel');

  // --- State ---
  var mode = 'analyze'; // 'analyze' | 'play'
  var playerColor = 'white';
  var gameMoves = []; // [{uci, san, fen}]
  var gameOver = false;
  var waitingForEngine = false;

  // Chess.js instance for client-side validation
  var game = new Chess();

  // Chessboard.js instance
  var board = Chessboard('board', {
    position: 'start',
    draggable: true,
    pieceTheme: '/static/vendor/img/{piece}.png',
    onDrop: onDrop,
    onSnapEnd: onSnapEnd,
  });

  // =========================================================================
  // Mode toggle
  // =========================================================================
  var modeBtns = document.querySelectorAll('.mode-btn');
  modeBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMode(btn.getAttribute('data-mode'));
    });
  });

  function setMode(newMode) {
    mode = newMode;
    modeBtns.forEach(function (btn) {
      var isActive = btn.getAttribute('data-mode') === mode;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    var isPlay = mode === 'play';
    analyzeControls.hidden = isPlay;
    playControls.hidden = !isPlay;
    moveListPanel.hidden = !isPlay;

    // Default: template ON in play mode (speed), OFF in analyze mode (depth)
    document.getElementById('templateToggle').checked = isPlay;

    if (isPlay) {
      coachingText.innerHTML = '<p class="placeholder">Choose your color to start playing.</p>';
      coachingMeta.textContent = '';
      userFeedback.hidden = true;
      colorModal.removeAttribute('hidden');
      colorModal.style.display = 'flex';
    } else {
      // Sync the current board position into the FEN input
      fenInput.value = game.fen();
      coachingText.innerHTML = '<p class="placeholder">Set up a position and click <strong>Analyze</strong> to get coaching.</p>';
      coachingMeta.textContent = '';
      userFeedback.hidden = true;
      clearArrows();
    }
  }

  // =========================================================================
  // Depth slider
  // =========================================================================
  depthSlider.addEventListener('input', function () {
    depthValue.textContent = depthSlider.value;
  });

  // =========================================================================
  // Strength slider (play mode)
  // =========================================================================
  function eloLabel(elo) {
    if (elo === 0) return 'Full strength';
    var titles = [
      [2400, 'GM'], [2300, 'IM'], [2200, 'FM'],
      [2000, 'CM'], [1800, 'Class B'], [1600, 'Class C'],
      [1400, 'Class D'], [1200, 'Novice'], [0, 'Beginner'],
    ];
    var title = 'Beginner';
    for (var i = 0; i < titles.length; i++) {
      if (elo >= titles[i][0]) { title = titles[i][1]; break; }
    }
    return 'Elo ' + elo + ' (' + title + ')';
  }

  strengthSlider.addEventListener('input', function () {
    strengthLabel.textContent = eloLabel(parseInt(strengthSlider.value));
  });

  strengthSlider.addEventListener('change', function () {
    var elo = parseInt(strengthSlider.value);
    fetch('/api/play/strength', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ play_elo: elo }),
    });
  });

  // =========================================================================
  // FEN input sync (analyze mode)
  // =========================================================================
  fenInput.addEventListener('change', function () {
    var fen = fenInput.value.trim();
    if (fen) {
      game.load(fen);
      board.position(fen.split(' ')[0]);
    }
  });

  // =========================================================================
  // Board drag-and-drop
  // =========================================================================
  function onDrop(source, target) {
    if (mode === 'play') return onDropPlay(source, target);
    return onDropAnalyze(source, target);
  }

  function onSnapEnd() {
    board.position(game.fen().split(' ')[0]);
  }

  function onDropAnalyze(source, target) {
    var move = game.move({ from: source, to: target, promotion: 'q' });
    if (move === null) return 'snapback';
    fenInput.value = game.fen();
  }

  function onDropPlay(source, target) {
    if (gameOver || waitingForEngine) return 'snapback';

    // Check it's the player's turn
    var turn = game.turn(); // 'w' or 'b'
    if ((playerColor === 'white' && turn !== 'w') ||
        (playerColor === 'black' && turn !== 'b')) {
      return 'snapback';
    }

    // Record FEN before the move for the server request
    var fenBeforeMove = game.fen();

    var move = game.move({ from: source, to: target, promotion: 'q' });
    if (move === null) return 'snapback';

    var uci = move.from + move.to + (move.promotion ? move.promotion : '');

    // Keep the move applied — don't undo. Board shows the piece where it landed.
    sendPlayMove(fenBeforeMove, uci, move.san, source + target);
  }

  // =========================================================================
  // Play mode: send move to server
  // =========================================================================
  function sendPlayMove(fenBeforeMove, userUci, userSan, rawUci) {
    waitingForEngine = true;
    setLoading(true, 'Evaluating your move…');
    clearArrows();
    userFeedback.hidden = true;
    hintContainer.hidden = true;
    clearDebug();
    appendDebug('Play move: FEN=' + fenBeforeMove + ' move=' + rawUci);

    // Record the user's move in gameMoves immediately (optimistic)
    gameMoves.push({ uci: rawUci, san: userSan, fen: game.fen() });
    renderMoveList();

    var useTemplate = document.getElementById('templateToggle').checked;

    if (useTemplate) {
      fetch('/api/play/move/template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fen: fenBeforeMove, user_move: rawUci }),
      })
        .then(function (res) {
          if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Move failed'); });
          return res.json();
        })
        .then(function (data) {
          handlePlayMoveResponse(data);
        })
        .catch(function (err) {
          handlePlayMoveError(err);
        })
        .finally(function () {
          waitingForEngine = false;
          setLoading(false);
        });
      return;
    }

    fetch('/api/play/move/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fen: fenBeforeMove, user_move: rawUci }),
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Move failed'); });
        return readSSE(res, function (event, data) {
          if (event === 'progress') {
            setLoading(true, data.message);
            var toolTag = data.tool ? '[' + data.tool + '] ' : '';
            appendDebug(toolTag + data.message);
            if (data.detail) appendDebugDetail('detail', data.detail);
          }
        });
      })
      .then(function (data) {
        if (!data) return;
        handlePlayMoveResponse(data);
      })
      .catch(function (err) {
        handlePlayMoveError(err);
      })
      .finally(function () {
        waitingForEngine = false;
        setLoading(false);
      });
  }

  function handlePlayMoveResponse(data) {
        // Show debug trace if available
        if (data.debug && data.debug.trace) {
          data.debug.trace.forEach(function (line) {
            appendDebug('[template] ' + line);
          });
        }

        // Show user feedback badge
        showUserFeedback(data.user_classification, data.user_feedback);

        // Apply engine move
        if (data.engine_move_uci) {
          var engineMove = game.move({
            from: data.engine_move_uci.substring(0, 2),
            to: data.engine_move_uci.substring(2, 4),
            promotion: data.engine_move_uci.length > 4 ? data.engine_move_uci[4] : undefined,
          });
          var engineSan = engineMove ? engineMove.san : data.engine_move;
          gameMoves.push({ uci: data.engine_move_uci, san: engineSan, fen: game.fen() });
        }

        board.position(game.fen().split(' ')[0]);
        updateEvalBar(data.eval_score);
        renderMoveList();

        // Show coaching text
        coachingMeta.textContent = data.opening_name || '';
        coachingText.innerHTML = renderMarkdown(data.coaching_text || '');

        // Show hint button if hint available
        if (data.hint_san) {
          hintText.textContent = 'Consider playing: ' + data.hint_san;
          hintText.hidden = true;
          hintBtn.textContent = '💡 Show hint';
          hintContainer.hidden = false;
        } else {
          hintContainer.hidden = true;
        }

        appendDebug('--- Done ---');

        // Game over?
        if (data.game_over) {
          gameOver = true;
          showGameResult(data.result);
        }
  }

  function handlePlayMoveError(err) {
        coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
        appendDebug('ERROR: ' + err.message);
        // Roll back the optimistic user move
        gameMoves.pop();
        game.undo();
        board.position(game.fen().split(' ')[0]);
        renderMoveList();
  }

  // =========================================================================
  // User feedback badge
  // =========================================================================
  function showUserFeedback(classification, text) {
    var badges = {
      good: '✓ Good',
      inaccuracy: '?! Inaccuracy',
      blunder: '?? Blunder',
    };
    var cls = 'feedback-' + (classification || 'good');
    userFeedback.className = 'user-feedback ' + cls;
    userFeedback.innerHTML = '<span class="badge">' + (badges[classification] || classification) +
      '</span> <span class="feedback-text">' + escapeHtml(text || '') + '</span>';
    userFeedback.hidden = false;
  }

  // =========================================================================
  // Move list
  // =========================================================================
  function renderMoveList() {
    var html = '';
    for (var i = 0; i < gameMoves.length; i += 2) {
      var moveNum = Math.floor(i / 2) + 1;
      var whiteMove = gameMoves[i];
      var blackMove = gameMoves[i + 1];
      var isLast = (i + 2 >= gameMoves.length);

      html += '<div class="move-pair' + (isLast ? ' current' : '') + '">';
      html += '<span class="move-num">' + moveNum + '.</span>';
      html += '<span class="move-san">' + escapeHtml(whiteMove.san) + '</span>';
      if (blackMove) {
        html += '<span class="move-san">' + escapeHtml(blackMove.san) + '</span>';
      }
      html += '</div>';
    }
    moveList.innerHTML = html;
    // Auto-scroll to bottom
    moveList.scrollTop = moveList.scrollHeight;
  }

  // =========================================================================
  // Game result display
  // =========================================================================
  function showGameResult(result) {
    gameResult.textContent = result || 'Game Over';
    gameResult.hidden = false;
    undoBtn.disabled = true;
  }

  // =========================================================================
  // New game
  // =========================================================================
  newGameBtn.addEventListener('click', function () {
    colorModal.removeAttribute('hidden');
    colorModal.style.display = 'flex';
  });

  document.querySelectorAll('.color-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      console.log('Color chosen:', btn.getAttribute('data-color'));
      colorModal.setAttribute('hidden', '');
      colorModal.style.display = 'none';
      startNewGame(btn.getAttribute('data-color'));
    });
  });

  function startNewGame(color) {
    playerColor = color;
    gameMoves = [];
    gameOver = false;
    game.reset();
    board.orientation(color);
    board.position('start');
    moveList.innerHTML = '';
    gameResult.hidden = true;
    undoBtn.disabled = false;
    userFeedback.hidden = true;
    coachingText.innerHTML = '<p class="placeholder">Your move…</p>';
    coachingMeta.textContent = '';
    evalFill.style.height = '50%';
    clearArrows();

    if (color === 'black') {
      // Engine moves first
      waitingForEngine = true;
      setLoading(true);
      fetch('/api/play/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ color: 'black' }),
      })
        .then(function (res) {
          if (!res.ok) throw new Error('Failed to start game');
          return res.json();
        })
        .then(function (data) {
          if (data.engine_move_uci) {
            game.load('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
            var engineMove = game.move({
              from: data.engine_move_uci.substring(0, 2),
              to: data.engine_move_uci.substring(2, 4),
              promotion: data.engine_move_uci.length > 4 ? data.engine_move_uci[4] : undefined,
            });
            var engineSan = engineMove ? engineMove.san : data.engine_move;
            gameMoves.push({ uci: data.engine_move_uci, san: engineSan, fen: game.fen() });
            board.position(game.fen().split(' ')[0]);
            renderMoveList();
            if (data.coaching_text) {
              coachingText.innerHTML = renderMarkdown(data.coaching_text);
            }
          }
        })
        .catch(function (err) {
          coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
        })
        .finally(function () {
          waitingForEngine = false;
          setLoading(false);
        });
    }
  }

  // =========================================================================
  // Undo
  // =========================================================================
  undoBtn.addEventListener('click', function () {
    if (gameMoves.length < 2 || gameOver || waitingForEngine) return;

    var uciList = gameMoves.map(function (m) { return m.uci; });
    var currentFen = game.fen();

    setLoading(true);
    fetch('/api/play/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fen: currentFen, moves: uciList }),
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Undo failed'); });
        return res.json();
      })
      .then(function (data) {
        // Truncate gameMoves to match returned moves
        gameMoves = gameMoves.slice(0, data.moves.length);
        game.load(data.fen);
        board.position(data.fen.split(' ')[0]);
        updateEvalBar(data.eval_score);
        renderMoveList();
        userFeedback.hidden = true;
        coachingText.innerHTML = '<p class="placeholder">Your move…</p>';
      })
      .catch(function (err) {
        coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
      })
      .finally(function () {
        setLoading(false);
      });
  });

  // =========================================================================
  // Analyze button (analyze mode)
  // =========================================================================
  analyzeBtn.addEventListener('click', function () {
    analyze();
  });

  // =========================================================================
  // Hint toggle
  // =========================================================================
  hintBtn.addEventListener('click', function () {
    if (hintText.hidden) {
      hintText.hidden = false;
      hintBtn.textContent = '💡 Hide hint';
    } else {
      hintText.hidden = true;
      hintBtn.textContent = '💡 Show hint';
    }
  });

  function analyze() {
    var fen = fenInput.value.trim();
    if (!fen) return;

    var useTemplate = document.getElementById('templateToggle').checked;

    setLoading(true, useTemplate ? 'Template analyzing…' : 'Engine analyzing…');
    clearArrows();
    clearDebug();
    appendDebug('Analyze request: FEN=' + fen + ' depth=' + depthSlider.value + ' level=' + levelSelect.value + (useTemplate ? ' [template]' : ''));

    if (useTemplate) {
      fetch('/api/analyze/template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fen: fen,
          depth: parseInt(depthSlider.value, 10),
          level: levelSelect.value,
        }),
      })
        .then(function (res) {
          if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || res.status); });
          return res.json();
        })
        .then(function (data) {
          renderCoaching(data);
          updateEvalBar(data.score);
          if (data.best_move) drawBestMoveArrow(data.best_move);
          appendDebug('--- Done (template, ' + (data.debug ? data.debug.total_s : '?') + 's) ---');
        })
        .catch(function (err) {
          coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
          appendDebug('ERROR: ' + err.message);
        })
        .finally(function () {
          setLoading(false);
        });
      return;
    }

    fetch('/api/analyze/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fen: fen,
        depth: parseInt(depthSlider.value, 10),
        level: levelSelect.value,
      }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error('Analysis failed (' + res.status + ')');
        return readSSE(res, function (event, data) {
          if (event === 'progress') {
            setLoading(true, data.message);
            var toolTag = data.tool ? '[' + data.tool + '] ' : '';
            appendDebug(toolTag + data.message);
            if (data.detail) appendDebugDetail('detail', data.detail);
          }
        });
      })
      .then(function (finalData) {
        if (finalData) {
          renderCoaching(finalData);
          updateEvalBar(finalData.score);
          if (finalData.best_move) drawBestMoveArrow(finalData.best_move);
          appendDebug('--- Done ---');
        }
      })
      .catch(function (err) {
        coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
        appendDebug('ERROR: ' + err.message);
      })
      .finally(function () {
        setLoading(false);
      });
  }

  // =========================================================================
  // Render coaching text (analyze mode)
  // =========================================================================
  function renderCoaching(data) {
    var meta = 'Best move: ' + (data.best_move || '?') + '  (' + (data.score || '?') + ')';
    if (data.opening_name) {
      meta = data.opening_name + '  |  ' + meta;
    }
    coachingMeta.textContent = meta;
    coachingText.innerHTML = renderMarkdown(data.coaching_text || '');
  }

  // =========================================================================
  // Eval bar
  // =========================================================================
  function updateEvalBar(scoreStr) {
    var cp = parseFloat(scoreStr) * 100;
    if (isNaN(cp)) cp = 0;
    cp = Math.max(-500, Math.min(500, cp));
    var pct = 50 + (cp / 500) * 50;
    evalFill.style.height = pct + '%';
  }

  // =========================================================================
  // Arrow drawing
  // =========================================================================
  function clearArrows() {
    arrowSvg.innerHTML = '';
  }

  function drawBestMoveArrow(moveStr) {
    if (!moveStr || moveStr.length < 4) return;
    var from = moveStr.substring(0, 2);
    var to = moveStr.substring(2, 4);
    drawArrow(from, to, '#22c55e');
  }

  function drawArrow(from, to, color) {
    var boardEl = document.getElementById('board');
    if (!boardEl) return;
    var rect = boardEl.getBoundingClientRect();
    var sqSize = rect.width / 8;

    var fromCoords = squareToCoords(from, sqSize);
    var toCoords = squareToCoords(to, sqSize);

    arrowSvg.setAttribute('width', rect.width);
    arrowSvg.setAttribute('height', rect.height);
    arrowSvg.style.left = rect.left + 'px';
    arrowSvg.style.top = rect.top + 'px';

    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', fromCoords.x);
    line.setAttribute('y1', fromCoords.y);
    line.setAttribute('x2', toCoords.x);
    line.setAttribute('y2', toCoords.y);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', '6');
    line.setAttribute('stroke-opacity', '0.7');
    line.setAttribute('marker-end', 'url(#arrowhead)');

    if (!arrowSvg.querySelector('defs')) {
      var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      var marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
      marker.setAttribute('id', 'arrowhead');
      marker.setAttribute('markerWidth', '10');
      marker.setAttribute('markerHeight', '7');
      marker.setAttribute('refX', '10');
      marker.setAttribute('refY', '3.5');
      marker.setAttribute('orient', 'auto');
      var polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      polygon.setAttribute('points', '0 0, 10 3.5, 0 7');
      polygon.setAttribute('fill', color);
      marker.appendChild(polygon);
      defs.appendChild(marker);
      arrowSvg.appendChild(defs);
    }

    arrowSvg.appendChild(line);
  }

  function squareToCoords(sq, sqSize) {
    var file = sq.charCodeAt(0) - 97;
    var rank = parseInt(sq[1], 10) - 1;
    // Flip coordinates when board is oriented for Black
    var orientation = board.orientation();
    if (orientation === 'black') {
      file = 7 - file;
      rank = 7 - rank;
    }
    return {
      x: file * sqSize + sqSize / 2,
      y: (7 - rank) * sqSize + sqSize / 2,
    };
  }

  // =========================================================================
  // Helpers
  // =========================================================================
  function setLoading(on, message) {
    spinner.hidden = !on;
    analyzeBtn.disabled = on;
    var spinnerText = document.getElementById('spinnerText');
    if (spinnerText) spinnerText.textContent = message || 'Thinking…';
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(str) {
    // Simple markdown to HTML: handles bold, numbered lists, bullet lists, paragraphs
    var html = escapeHtml(str);
    // Bold: **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Split into lines for list handling
    var lines = html.split('\n');
    var out = [];
    var inOl = false;
    var inUl = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var olMatch = line.match(/^\s*(\d+)\.\s+(.*)/);
      var ulMatch = line.match(/^\s*[-*]\s+(.*)/);
      if (olMatch) {
        if (!inOl) { if (inUl) { out.push('</ul>'); inUl = false; } out.push('<ol>'); inOl = true; }
        out.push('<li>' + olMatch[2] + '</li>');
      } else if (ulMatch) {
        if (!inUl) { if (inOl) { out.push('</ol>'); inOl = false; } out.push('<ul>'); inUl = true; }
        out.push('<li>' + ulMatch[1] + '</li>');
      } else {
        if (inOl) { out.push('</ol>'); inOl = false; }
        if (inUl) { out.push('</ul>'); inUl = false; }
        if (line.trim() === '') {
          out.push('');
        } else {
          out.push('<p>' + line + '</p>');
        }
      }
    }
    if (inOl) out.push('</ol>');
    if (inUl) out.push('</ul>');
    return out.join('\n');
  }

  function showDebug(data) {
    if (data && debugContent) {
      debugContent.textContent = JSON.stringify(data, null, 2);
    }
  }

  function appendDebug(message) {
    if (debugContent) {
      if (debugContent.textContent === 'No data yet. Make a move or analyze a position.') {
        debugContent.textContent = '';
      }
      var ts = new Date().toLocaleTimeString();
      debugContent.textContent += '[' + ts + '] ' + message + '\n';
      debugContent.scrollTop = debugContent.scrollHeight;
    }
  }

  function appendDebugDetail(label, data) {
    if (debugContent && data) {
      var text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
      debugContent.textContent += '  ┗ ' + label + ': ' + text + '\n';
      debugContent.scrollTop = debugContent.scrollHeight;
    }
  }

  function clearDebug() {
    if (debugContent) {
      debugContent.textContent = '';
    }
  }

  /**
   * Read an SSE stream from a fetch Response.
   * Calls onEvent(eventName, parsedData) for each event.
   * Returns a promise that resolves with the 'done' event data,
   * or rejects if an 'error' event is received.
   */
  function readSSE(response, onEvent) {
    return new Promise(function (resolve, reject) {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      var doneData = null;

      function pump() {
        reader.read().then(function (result) {
          if (result.done) {
            resolve(doneData);
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          // Parse complete SSE messages (separated by double newline)
          var parts = buffer.split('\n\n');
          buffer = parts.pop() || '';
          parts.forEach(function (block) {
            if (!block.trim()) return;
            var eventName = 'message';
            var dataStr = '';
            block.split('\n').forEach(function (line) {
              if (line.indexOf('event: ') === 0) {
                eventName = line.substring(7);
              } else if (line.indexOf('data: ') === 0) {
                dataStr += line.substring(6);
              }
            });
            if (!dataStr) return;
            try {
              var parsed = JSON.parse(dataStr);
            } catch (e) {
              return;
            }
            if (eventName === 'error') {
              reject(new Error(parsed.message || 'Server error'));
              return;
            }
            if (eventName === 'done') {
              doneData = parsed;
            }
            if (onEvent) onEvent(eventName, parsed);
          });
          pump();
        }).catch(reject);
      }
      pump();
    });
  }
})();
