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
  var moveList = document.getElementById('moveList');
  var gameResult = document.getElementById('gameResult');
  var newGameBtn = document.getElementById('newGameBtn');
  var undoBtn = document.getElementById('undoBtn');
  var colorModal = document.getElementById('colorModal');

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

    if (isPlay) {
      coachingText.innerHTML = '<p class="placeholder">Start a new game to begin playing.</p>';
      coachingMeta.textContent = '';
      userFeedback.hidden = true;
    } else {
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

    var move = game.move({ from: source, to: target, promotion: 'q' });
    if (move === null) return 'snapback';

    var uci = move.from + move.to + (move.promotion ? move.promotion : '');
    var fenBefore = game.fen();

    // Undo the move on chess.js — we'll re-apply after server confirms
    game.undo();

    sendPlayMove(fenBefore, uci, move.san, source + target);
  }

  // =========================================================================
  // Play mode: send move to server
  // =========================================================================
  function sendPlayMove(fenBeforeEngineReply, userUci, userSan, rawUci) {
    // The FEN we send is the position BEFORE the user's move
    var fenToSend = gameMoves.length > 0
      ? gameMoves[gameMoves.length - 1].fen
      : 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

    waitingForEngine = true;
    setLoading(true);
    clearArrows();
    userFeedback.hidden = true;

    fetch('/api/play/move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fen: fenToSend, user_move: rawUci }),
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || 'Move failed'); });
        return res.json();
      })
      .then(function (data) {
        // Re-apply user move on chess.js
        game.load(fenToSend);
        var userMoveObj = game.move({ from: rawUci.substring(0, 2), to: rawUci.substring(2, 4), promotion: 'q' });
        var userSanActual = userMoveObj ? userMoveObj.san : userSan;

        gameMoves.push({ uci: rawUci, san: userSanActual, fen: game.fen() });

        // Show user feedback badge
        showUserFeedback(data.user_classification, data.user_feedback);

        // Apply engine move
        if (data.engine_move_uci && !data.game_over) {
          var engineMove = game.move({
            from: data.engine_move_uci.substring(0, 2),
            to: data.engine_move_uci.substring(2, 4),
            promotion: data.engine_move_uci.length > 4 ? data.engine_move_uci[4] : undefined,
          });
          var engineSan = engineMove ? engineMove.san : data.engine_move;
          gameMoves.push({ uci: data.engine_move_uci, san: engineSan, fen: game.fen() });
        } else if (data.engine_move_uci && data.game_over) {
          // Engine delivered checkmate or game ended
          var engineMove2 = game.move({
            from: data.engine_move_uci.substring(0, 2),
            to: data.engine_move_uci.substring(2, 4),
            promotion: data.engine_move_uci.length > 4 ? data.engine_move_uci[4] : undefined,
          });
          var engineSan2 = engineMove2 ? engineMove2.san : data.engine_move;
          gameMoves.push({ uci: data.engine_move_uci, san: engineSan2, fen: game.fen() });
        }

        board.position(game.fen().split(' ')[0]);
        updateEvalBar(data.eval_score);
        renderMoveList();

        // Show coaching text
        coachingMeta.textContent = '';
        coachingText.innerHTML = '<p>' + escapeHtml(data.coaching_text || '') + '</p>';

        // Game over?
        if (data.game_over) {
          gameOver = true;
          showGameResult(data.result);
        }
      })
      .catch(function (err) {
        coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
        // Restore board position
        board.position(game.fen().split(' ')[0]);
      })
      .finally(function () {
        waitingForEngine = false;
        setLoading(false);
      });
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
              coachingText.innerHTML = '<p>' + escapeHtml(data.coaching_text) + '</p>';
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

  function analyze() {
    var fen = fenInput.value.trim();
    if (!fen) return;

    setLoading(true);
    clearArrows();

    fetch('/api/analyze', {
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
        return res.json();
      })
      .then(function (data) {
        renderCoaching(data);
        updateEvalBar(data.score);
        if (data.best_move) drawBestMoveArrow(data.best_move);
      })
      .catch(function (err) {
        coachingText.innerHTML = '<p class="error">Error: ' + escapeHtml(err.message) + '</p>';
      })
      .finally(function () {
        setLoading(false);
      });
  }

  // =========================================================================
  // Render coaching text (analyze mode)
  // =========================================================================
  function renderCoaching(data) {
    coachingMeta.textContent =
      'Best move: ' + (data.best_move || '?') + '  (' + (data.score || '?') + ')';
    coachingText.innerHTML = '<p>' + escapeHtml(data.coaching_text || '') + '</p>';
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
    return {
      x: file * sqSize + sqSize / 2,
      y: (7 - rank) * sqSize + sqSize / 2,
    };
  }

  // =========================================================================
  // Helpers
  // =========================================================================
  function setLoading(on) {
    spinner.hidden = !on;
    analyzeBtn.disabled = on;
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
})();
