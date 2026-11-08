"use strict";

// One player per browser tab (sessionStorage), so two tabs can play each other.
const POLL_MS = 1000;
const WAKE_RETRY_MS = 5000;
// Empty when this page is served by the game server itself; set in static/config.js
// when the page is hosted elsewhere (GitHub Pages) and talks to a remote server.
const API_BASE = String(window.IMPOSTOR_API_BASE || "").replace(/\/+$/, "");
const $ = (id) => document.getElementById(id);

const state = {
  playerId: sessionStorage.getItem("impostor.playerId"),
  nickname: sessionStorage.getItem("impostor.nickname"),
  gameId: null,
  lastSeq: 0,
  status: null,
  endsAt: 0,
  roundSeconds: 120,
  pollTimer: null,
  tickTimer: null,
  busy: false,
  guessingEarly: false,
};

class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, body, method = body ? "POST" : "GET") {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Can't reach the game server. Check your connection and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Something went wrong.";
    throw new ApiError(res.status, detail);
  }
  return data;
}

function show(screen) {
  for (const id of ["screen-lobby", "screen-search", "screen-game"]) $(id).hidden = id !== screen;
}

function stopTimers() {
  clearTimeout(state.pollTimer);
  clearInterval(state.tickTimer);
  state.pollTimer = null;
  state.tickTimer = null;
}

function renderMe(stats) {
  if (!state.nickname) { $("me").hidden = true; return; }
  const me = $("me");
  me.hidden = false;
  me.textContent = "";
  const name = document.createElement("b");
  name.textContent = state.nickname;
  me.append(name);
  if (stats) me.append(` · ${stats.score} pts · streak ${stats.streak}`);
}

function forgetPlayer() {
  sessionStorage.removeItem("impostor.playerId");
  state.playerId = null;
}

function handleError(err, target) {
  if (err instanceof ApiError && err.status === 404 && /player/i.test(err.message)) {
    // Server restarted: start over in the lobby.
    forgetPlayer();
    stopTimers();
    toLobby("The server restarted. Pick your nickname again.");
    return;
  }
  if (target) $(target).textContent = err.message;
  else console.error(err);
}

/* ---------------------------------------------------------------- lobby */
function setServerReady(ready) {
  $("join-form").querySelector("button").disabled = !ready;
  $("server-status").hidden = ready;
}

// Free hosts put the server to sleep when idle; the first request wakes it (can take a minute).
async function waitForServer() {
  for (;;) {
    try {
      await api("/api/health");
      setServerReady(true);
      return;
    } catch {
      setServerReady(false);
      await new Promise((resolve) => setTimeout(resolve, WAKE_RETRY_MS));
    }
  }
}

async function refreshLobby() {
  try {
    const [board, stats, health] = await Promise.all([
      api("/api/leaderboard"), api("/api/stats"), api("/api/health"),
    ]);
    const list = $("leaderboard");
    list.textContent = "";
    if (!board.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No games yet. Be first.";
      list.append(li);
    }
    for (const p of board) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = p.nickname;
      const score = document.createElement("span");
      score.textContent = `${p.score} pts · ${p.correct}/${p.games_played}`;
      li.append(name, score);
      list.append(li);
    }
    const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
    const rows = [
      ["Games played", stats.games_finished],
      ["Spot-the-AI accuracy", pct(stats.spot_the_ai_accuracy)],
      ["Spot-the-human accuracy", pct(stats.spot_the_human_accuracy)],
      ["AI fooled players", pct(stats.ai_fool_rate)],
    ];
    const dl = $("stats");
    dl.textContent = "";
    for (const [k, v] of rows) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }
    $("runtime").textContent = health.mode === "databricks"
      ? "The AI runs on Databricks Model Serving. Games are logged to Unity Catalog."
      : "Offline demo mode (mock AI, local log).";
  } catch (err) {
    handleError(err);
  }
}

function toLobby(message = "") {
  stopTimers();
  state.gameId = null;
  show("screen-lobby");
  $("join-error").textContent = message;
  if (state.nickname) $("nickname").value = state.nickname;
  renderMe();
  refreshLobby();
}

async function join(event) {
  event.preventDefault();
  const nickname = $("nickname").value.trim();
  if (!nickname) return;
  $("join-error").textContent = "";
  try {
    if (!state.playerId || nickname !== state.nickname) {
      const res = await api("/api/players", { nickname });
      state.playerId = res.player_id;
      state.nickname = res.nickname;
      sessionStorage.setItem("impostor.playerId", state.playerId);
      sessionStorage.setItem("impostor.nickname", state.nickname);
    }
    renderMe();
    await findMatch();
  } catch (err) {
    handleError(err, "join-error");
  }
}

/* ------------------------------------------------------------ matching */
async function findMatch() {
  stopTimers();
  show("screen-search");
  try {
    const res = await api("/api/match", { player_id: state.playerId });
    onMatchStatus(res);
  } catch (err) {
    handleError(err, "join-error");
    if (state.playerId) toLobby(err.message);
  }
}

function onMatchStatus(res) {
  if (res.status === "matched") return enterGame(res.game_id);
  if (res.status === "idle") return toLobby();
  state.pollTimer = setTimeout(pollMatch, POLL_MS);
}

async function pollMatch() {
  try {
    onMatchStatus(await api("/api/match/poll", { player_id: state.playerId }));
  } catch (err) {
    handleError(err);
    state.pollTimer = setTimeout(pollMatch, POLL_MS * 2);
  }
}

async function cancelSearch() {
  stopTimers();
  try { await api("/api/match/cancel", { player_id: state.playerId }); } catch (err) { handleError(err); }
  toLobby();
}

/* ---------------------------------------------------------------- game */
function enterGame(gameId) {
  stopTimers();
  state.gameId = gameId;
  state.lastSeq = 0;
  state.status = "chatting";
  state.guessingEarly = false;
  $("messages").textContent = "";
  addSystemLine("You're connected. Say hi — or wait and see who talks first.");
  $("guess-panel").hidden = true;
  $("result-panel").hidden = true;
  $("message-form").hidden = false;
  $("guess-early").hidden = false;
  $("chat-error").textContent = "";
  setComposerEnabled(true);
  show("screen-game");
  $("message-input").focus();
  state.tickTimer = setInterval(tick, 250);
  pollGame();
}

function addSystemLine(text) {
  const li = document.createElement("li");
  li.className = "system";
  li.textContent = text;
  $("messages").append(li);
}

function addMessage(msg) {
  const li = document.createElement("li");
  li.className = msg.from === "me" ? "me" : "them";
  li.textContent = msg.text;
  const list = $("messages");
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  list.append(li);
  if (nearBottom || msg.from === "me") list.scrollTop = list.scrollHeight;
}

function setComposerEnabled(enabled) {
  $("message-input").disabled = !enabled;
  $("message-form").querySelector("button").disabled = !enabled;
}

function tick() {
  const left = state.status === "chatting" ? Math.max(0, (state.endsAt - Date.now()) / 1000) : 0;
  const m = Math.floor(left / 60);
  const s = Math.floor(left % 60).toString().padStart(2, "0");
  $("timer").textContent = `${m}:${s}`;
  $("timer").classList.toggle("low", left <= 15);
  $("progress-bar").style.width = `${(left / state.roundSeconds) * 100}%`;
}

async function pollGame() {
  if (!state.gameId) return;
  const gameId = state.gameId;
  try {
    const view = await api(`/api/games/${gameId}/state?since=${state.lastSeq}`, { player_id: state.playerId });
    if (gameId !== state.gameId) return;
    applyView(view);
  } catch (err) {
    handleError(err, "chat-error");
  }
  if (state.gameId === gameId && state.status !== "revealed") {
    state.pollTimer = setTimeout(pollGame, POLL_MS);
  }
}

function applyView(view) {
  for (const msg of view.messages) {
    if (msg.seq > state.lastSeq) {
      addMessage(msg);
      state.lastSeq = msg.seq;
    }
  }
  state.roundSeconds = view.round_seconds;
  state.endsAt = Date.now() + view.seconds_left * 1000;
  renderMe(view.player);
  // After "guess now" the server still says chatting until the guess lands; keep the guess UI.
  if (state.guessingEarly && view.status === "chatting") return;
  if (view.status !== state.status) {
    state.status = view.status;
    if (view.status === "guessing") showGuess(view.closed_reason);
    if (view.status === "revealed") showResult(view.reveal, view.player);
  }
}

function showGuess(reason) {
  setComposerEnabled(false);
  $("message-form").hidden = true;
  $("guess-early").hidden = true;
  const titles = {
    timer: "Time's up. Who were you talking to?",
    partner_ended: "The stranger ended the chat. Who were they?",
    you_guessed: "Chat closed. Lock in your guess.",
  };
  $("guess-title").textContent = titles[reason] || titles.timer;
  addSystemLine("Chat closed.");
  for (const b of document.querySelectorAll(".choice")) b.disabled = false;
  $("guess-panel").hidden = false;
  $("guess-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showResult(reveal, player) {
  stopTimers();
  $("guess-panel").hidden = true;
  $("message-form").hidden = true;
  $("guess-early").hidden = true;
  const badge = $("result-badge");
  if (reveal.correct === null) {
    badge.className = "badge";
    badge.textContent = "No guess";
  } else {
    badge.className = `badge ${reveal.correct ? "correct" : "wrong"}`;
    badge.textContent = reveal.correct ? "Correct" : "Fooled!";
  }
  $("result-title").textContent = reveal.opponent_type === "ai"
    ? `It was an AI playing "${reveal.opponent_name}".`
    : `It was a real human: ${reveal.opponent_name}.`;
  $("result-detail").textContent = reveal.detail || "";
  $("result-points").textContent = reveal.points
    ? `+${reveal.points} points · streak ${player.streak}`
    : `Streak reset · ${player.score} pts total`;
  $("result-panel").hidden = false;
  $("play-again").focus();
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("message-input");
  const text = input.value.trim();
  if (!text || state.busy || state.status !== "chatting") return;
  state.busy = true;
  $("chat-error").textContent = "";
  try {
    await api(`/api/games/${state.gameId}/messages`, { player_id: state.playerId, text });
    input.value = "";
    clearTimeout(state.pollTimer);
    pollGame();
  } catch (err) {
    handleError(err, "chat-error");
  } finally {
    state.busy = false;
    input.focus();
  }
}

async function guess(choice) {
  for (const b of document.querySelectorAll(".choice")) b.disabled = true;
  try {
    const view = await api(`/api/games/${state.gameId}/guess`, { player_id: state.playerId, guess: choice });
    applyView(view);
  } catch (err) {
    handleError(err, "chat-error");
    for (const b of document.querySelectorAll(".choice")) b.disabled = false;
  }
}

function guessEarly() {
  if (state.status !== "chatting") return;
  state.status = "guessing";
  state.guessingEarly = true;
  showGuess("you_guessed");
}

/* ---------------------------------------------------------------- wire */
$("join-form").addEventListener("submit", join);
$("cancel-search").addEventListener("click", cancelSearch);
$("message-form").addEventListener("submit", sendMessage);
$("guess-early").addEventListener("click", guessEarly);
$("play-again").addEventListener("click", findMatch);
$("back-lobby").addEventListener("click", () => toLobby());
for (const b of document.querySelectorAll(".choice")) {
  b.addEventListener("click", () => guess(b.dataset.guess));
}
toLobby();
waitForServer().then(refreshLobby);
