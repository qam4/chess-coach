/* Chess Coach — main application script */

(function () {
  'use strict';

  // DOM elements
  var fenInput = document.getElementById('fenInput');
  var depthSlider = document.getElementById('depthSlider');
  var depthValue = document.getElementById('depthValue');
  var levelSelect = document.getElementById('levelSelect');
  var analyzeBtn = document.getElementById('analyzeBtn');
  var coachingText = document.getElementById('coachingText');
  var coachingMeta = document.getElementById('coachingMeta');
  var spinner = document.getElementById('spinner');
  var evalFill = document.getElementById('evalFill');
  var arrowSvg = document.getElementById('arrowSvg');

  // Chess.js instance for client-side validation
  var game = new Chess();

  // Chessboard.js instance
  var board = Chessboard('board', {
    position: 'start',
    draggable: true,
    pieceTheme: '/static/vendor/img/{piece}.svg',
    onDrop: onDrop,
    onSnapEnd: onSnapEnd,
  });

  // --- Depth slider ---
  depthSlider.addEventListener('input', function () {
    depthValue.textContent = depthSlider.value;
  });

  // --- FEN input sync ---
  fenInput.addEventListener('change', function () {
    var fen = fenInput.value.trim();
    if (fen) {
      game.load(fen);
      board.position(fen.split(' ')[0]);
    }
  });

  // --- Board drag-and-drop ---
  function onDrop(source, target) {
    var move = game.move({ from: source, to: target, promotion: 'q' });
    if (move === null) return 'snapback';
    fenInput.value = game.fen();
  }

  function onSnapEnd() {
    board.position(game.fen().split(' ')[0]);
  }

  // --- Analyze button ---
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
        coachingText.innerHTML =
          '<p class="error">Error: ' + err.message + '</p>';
      })
      .finally(function () {
        setLoading(false);
      });
  }

  // --- Render coaching text ---
  function renderCoaching(data) {
    coachingMeta.textContent =
      'Best move: ' + (data.best_move || '?') + '  (' + (data.score || '?') + ')';
    coachingText.innerHTML = '<p>' + escapeHtml(data.coaching_text || '') + '</p>';
  }

  // --- Eval bar ---
  function updateEvalBar(scoreStr) {
    // scoreStr is like "+0.35" or "-1.20" or "#±N"
    var cp = parseFloat(scoreStr) * 100;
    if (isNaN(cp)) cp = 0;
    // Clamp to ±500 cp for display
    cp = Math.max(-500, Math.min(500, cp));
    // Convert to percentage: 50% = equal, 100% = white winning
    var pct = 50 + (cp / 500) * 50;
    evalFill.style.height = pct + '%';
  }

  // --- Arrow drawing ---
  function clearArrows() {
    arrowSvg.innerHTML = '';
  }

  function drawBestMoveArrow(moveStr) {
    // moveStr is in coordinate notation, e.g. "e2e4"
    if (!moveStr || moveStr.length < 4) return;
    var from = moveStr.substring(0, 2);
    var to = moveStr.substring(2, 4);
    drawArrow(from, to, '#22c55e');
  }

  function drawArrow(from, to, color) {
    // Get board element position for coordinate mapping
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

    // Add arrowhead marker if not present
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
    var file = sq.charCodeAt(0) - 97; // a=0, h=7
    var rank = parseInt(sq[1], 10) - 1; // 1=0, 8=7
    return {
      x: file * sqSize + sqSize / 2,
      y: (7 - rank) * sqSize + sqSize / 2,
    };
  }

  // --- Helpers ---
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
