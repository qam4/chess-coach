/*
 * chessboard.js v1.0.0 — STUB
 *
 * Download the real library from: https://chessboardjs.com/
 * Place the minified JS file here to replace this stub.
 *
 * License: BSD-2-Clause
 *
 * This stub provides the minimum API surface so the app loads
 * without errors. It will NOT render a real board.
 */

/* global window, document */

(function () {
  'use strict';

  function Chessboard(containerId, config) {
    var containerEl =
      typeof containerId === 'string'
        ? document.getElementById(containerId)
        : containerId;

    config = config || {};

    var currentPosition = config.position || 'start';

    function positionToFen(pos) {
      if (pos === 'start') {
        return 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
      }
      if (typeof pos === 'string') return pos.split(' ')[0];
      return '';
    }

    if (containerEl) {
      containerEl.innerHTML =
        '<div style="width:100%;aspect-ratio:1;background:#b58863;' +
        'display:flex;align-items:center;justify-content:center;' +
        'color:#fff;font-size:14px;text-align:center;">' +
        'Chessboard stub — replace with real chessboard.js</div>';
    }

    return {
      position: function (pos) {
        if (pos === undefined) return currentPosition;
        currentPosition = pos;
      },
      fen: function () {
        return positionToFen(currentPosition);
      },
      move: function () {},
      orientation: function (side) {
        if (side === undefined) return config.orientation || 'white';
      },
      resize: function () {},
      destroy: function () {},
      clear: function () { currentPosition = '8/8/8/8/8/8/8/8'; },
      start: function () { currentPosition = 'start'; },
    };
  }

  // Expose globally
  window.Chessboard = Chessboard;
})();
