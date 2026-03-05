/*
 * chess.js v0.13.4 — STUB
 *
 * Download the real library from: https://github.com/jhlywa/chess.js
 * Place the built JS file here to replace this stub.
 *
 * License: BSD-2-Clause
 *
 * This stub provides the minimum API surface so the app loads
 * without errors. It will NOT validate moves.
 */

/* global window */

(function () {
  'use strict';

  var DEFAULT_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

  function Chess(fen) {
    var currentFen = fen || DEFAULT_FEN;

    return {
      fen: function () { return currentFen; },
      load: function (f) { currentFen = f; return true; },
      move: function (m) { return m; },
      undo: function () { return null; },
      game_over: function () { return false; },
      in_check: function () { return false; },
      in_checkmate: function () { return false; },
      in_stalemate: function () { return false; },
      in_draw: function () { return false; },
      turn: function () { return currentFen.split(' ')[1] || 'w'; },
      validate_fen: function (f) { return { valid: true }; },
      moves: function () { return []; },
      reset: function () { currentFen = DEFAULT_FEN; },
    };
  }

  window.Chess = Chess;
})();
