"use strict";
// Group chat mode. Loaded after app.js and reuses its helpers:
// api, $, state, show, showSearch, stopTimers, ensurePlayer, handleError, renderMe, toLobby, POLL_MS.

const room = { endsAt: 0, voteEndsAt: 0, roundSeconds: 180, seatsKey: "" };

async function joinGroup() {
  if (await ensurePlayer()) await findRoom();
}

async function findRoom() {
  stopTimers();
  state.mode = "group";
  showSearch("Gathering a group…", "A few people. A few impostors. Nobody knows who's who.");
  try {
    onRoomStatus(await api("/api/rooms/join", { player_id: state.playerId }));
  } catch (err) {
    handleError(err, "join-error");
    if (state.playerId) toLobby(err.message);
  }
}

function onRoomStatus(res) {
  if (res.status === "matched") return enterRoom(res.room_id);
  if (res.status === "idle") return toLobby();
  state.pollTimer = setTimeout(pollRoomMatch, POLL_MS);
}

async function pollRoomMatch() {
  try {
    onRoomStatus(await api("/api/rooms/poll", { player_id: state.playerId }));
  } catch (err) {
    handleError(err);
    state.pollTimer = setTimeout(pollRoomMatch, POLL_MS * 2);
  }
}

function enterRoom(roomId) {
  stopTimers();
  state.roomId = roomId;
  state.lastSeq = 0;
  state.status = "chatting";
  room.seatsKey = "";
  $("room-messages").textContent = "";
  $("room-members").textContent = "";
  roomLine("You're in. Say hi to the group.");
  $("vote-panel").hidden = true;
  $("room-result").hidden = true;
  $("room-form").hidden = false;
  $("room-input").disabled = false;
  $("room-error").textContent = "";
  $("screen-room").classList.remove("closed");
  show("screen-room");
  $("room-input").focus();
  state.tickTimer = setInterval(roomTick, 250);
  pollRoomState();
}

async function pollRoomState() {
  const roomId = state.roomId;
  if (!roomId) return;
  try {
    const view = await api(`/api/rooms/${roomId}/state?since=${state.lastSeq}`, { player_id: state.playerId });
    if (roomId !== state.roomId) return;
    applyRoomView(view);
  } catch (err) {
    if (err.status === 404 && /room/i.test(err.message)) {
      toLobby("That room has closed.");  // purged after it ended; stop polling
      return;
    }
    handleError(err, "room-error");
  }
  if (state.roomId === roomId && state.status !== "revealed") {
    state.pollTimer = setTimeout(pollRoomState, POLL_MS);
  }
}

function applyRoomView(view) {
  renderMembers(view.seats);
  for (const msg of view.messages) {
    if (msg.seq > state.lastSeq) {
      roomMessage(msg, view.seats);
      state.lastSeq = msg.seq;
    }
  }
  room.roundSeconds = view.round_seconds;
  const now = Date.now();
  if (view.status === "chatting") room.endsAt = now + view.seconds_left * 1000;
  if (view.status === "voting") room.voteEndsAt = now + view.seconds_left * 1000;
  renderMe(view.player);
  if (view.status === state.status) return;
  state.status = view.status;
  if (view.status === "voting") showBallot(view.seats);
  if (view.status === "waiting") showWaiting();
  if (view.status === "revealed") showRoomReveal(view.reveal, view.player);
}

// You voted; the answers stay hidden until everyone else has voted too.
function showWaiting() {
  $("screen-room").classList.add("closed");
  $("room-form").hidden = true;
  $("vote-panel").hidden = true;
  $("room-result-title").textContent = "Your votes are in.";
  $("room-result-points").textContent = "Waiting for the others to vote…";
  $("reveal-list").textContent = "";
  $("room-again").hidden = true;
  $("room-result").hidden = false;
}

/* ----------------------------------------------------------------- chat */
function colorOf(seats, alias) {
  const seat = seats.find((s) => s.alias === alias);
  return seat ? seat.color : 0;
}

function renderMembers(seats) {
  const key = seats.map((s) => s.alias).join(",");
  if (key === room.seatsKey) return;
  room.seatsKey = key;
  const list = $("room-members");
  list.textContent = "";
  for (const seat of seats) {
    const li = document.createElement("li");
    li.className = `chip-alias c${seat.color}${seat.me ? " me" : ""}`;
    li.textContent = seat.me ? `${seat.alias} (you)` : seat.alias;
    list.append(li);
  }
}

function roomLine(text) {
  const li = document.createElement("li");
  li.className = "system";
  li.textContent = text;
  $("room-messages").append(li);
}

function roomMessage(msg, seats) {
  const list = $("room-messages");
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  const li = document.createElement("li");
  li.className = msg.from === "me" ? "me" : `them c${colorOf(seats, msg.alias)}`;
  if (msg.from !== "me") {
    const name = document.createElement("span");
    name.className = "who-said";
    name.textContent = msg.alias;
    li.append(name);
  }
  li.append(document.createTextNode(msg.text));
  list.append(li);
  if (nearBottom || msg.from === "me") list.scrollTop = list.scrollHeight;
}

async function sendRoomMessage(event) {
  event.preventDefault();
  const input = $("room-input");
  const text = input.value.trim();
  if (!text || state.busy || state.status !== "chatting") return;
  state.busy = true;
  $("room-error").textContent = "";
  try {
    await api(`/api/rooms/${state.roomId}/messages`, { player_id: state.playerId, text });
    input.value = "";
    clearTimeout(state.pollTimer);
    pollRoomState();
  } catch (err) {
    handleError(err, "room-error");
  } finally {
    state.busy = false;
    input.focus();
  }
}

function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function roomTick() {
  const now = Date.now();
  const left = state.status === "chatting" ? Math.max(0, (room.endsAt - now) / 1000) : 0;
  $("room-timer").textContent = formatClock(left);
  $("room-timer").classList.toggle("low", state.status === "chatting" && left <= 20);
  $("room-progress").style.width = `${(left / room.roundSeconds) * 100}%`;
  if (state.status === "voting") $("vote-timer").textContent = formatClock((room.voteEndsAt - now) / 1000);
}

/* ----------------------------------------------------------------- vote */
function showBallot(seats) {
  $("screen-room").classList.add("closed");
  $("room-form").hidden = true;
  roomLine("Chat closed. Time to vote.");
  const ballot = $("ballot");
  ballot.textContent = "";
  for (const seat of seats.filter((s) => !s.me)) {
    const li = document.createElement("li");
    const chip = document.createElement("span");
    chip.className = `chip-alias c${seat.color}`;
    chip.textContent = seat.alias;
    const seg = document.createElement("div");
    seg.className = "seg";
    seg.setAttribute("role", "radiogroup");
    seg.setAttribute("aria-label", `Is ${seat.alias} human or AI?`);
    for (const [value, label] of [["human", "Human"], ["ai", "AI"]]) {
      const lab = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `vote-${seat.alias}`;
      input.value = value;
      input.dataset.alias = seat.alias;
      input.addEventListener("change", updateVoteButton);
      lab.append(input, document.createTextNode(label));
      seg.append(lab);
    }
    li.append(chip, seg);
    ballot.append(li);
  }
  $("vote-error").textContent = "";
  updateVoteButton();
  $("vote-panel").hidden = false;
  $("vote-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function collectVotes() {
  const votes = {};
  for (const input of $("ballot").querySelectorAll("input:checked")) votes[input.dataset.alias] = input.value;
  return votes;
}

function updateVoteButton() {
  const needed = $("ballot").querySelectorAll("li").length;
  $("vote-submit").disabled = Object.keys(collectVotes()).length < needed;
}

async function submitVote(event) {
  event.preventDefault();
  $("vote-submit").disabled = true;
  try {
    const view = await api(`/api/rooms/${state.roomId}/vote`, { player_id: state.playerId, votes: collectVotes() });
    applyRoomView(view);
    if (state.status !== "revealed") {
      clearTimeout(state.pollTimer);
      state.pollTimer = setTimeout(pollRoomState, POLL_MS);
    }
  } catch (err) {
    handleError(err, "vote-error");
    updateVoteButton();
  }
}

/* --------------------------------------------------------------- reveal */
function showRoomReveal(reveal, player) {
  const firstShow = $("room-result").hidden;
  clearInterval(state.tickTimer);
  $("screen-room").classList.add("closed");
  $("room-form").hidden = true;
  $("vote-panel").hidden = true;
  const caught = reveal.seats.filter((s) => s.kind === "ai" && s.your_vote === "ai").length;
  const aiWord = reveal.ai_count === 1 ? "AI" : "AIs";
  $("room-result-title").textContent = reveal.total_marks
    ? `You caught ${caught} of ${reveal.ai_count} ${aiWord} · ${reveal.correct_marks}/${reveal.total_marks} marks right`
    : `There ${reveal.ai_count === 1 ? "was" : "were"} ${reveal.ai_count} ${aiWord} in this room`;
  $("room-result-points").textContent = reveal.points
    ? `+${reveal.points} points · ${player.score} total`
    : `No points this round · ${player.score} total`;
  const list = $("reveal-list");
  list.textContent = "";
  for (const seat of reveal.seats) list.append(revealRow(seat));
  $("room-again").hidden = false;
  $("room-result").hidden = false;
  if (firstShow) $("room-again").focus();
}

function revealRow(seat) {
  const li = document.createElement("li");
  li.className = seat.kind === "ai" ? "is-ai" : "is-human";
  const chip = document.createElement("span");
  chip.className = `chip-alias c${seat.color}`;
  chip.textContent = seat.me ? `${seat.alias} (you)` : seat.alias;
  const body = document.createElement("div");
  body.className = "reveal-body";
  const who = document.createElement("strong");
  who.textContent = seat.kind === "ai" ? `AI playing "${seat.name}"` : `Human: ${seat.name}`;
  const meta = document.createElement("span");
  meta.className = "muted";
  const voteText = seat.votes ? `${seat.voted_ai} of ${seat.votes} voted AI` : "No votes";
  meta.textContent = seat.detail ? `${voteText} · ${seat.detail}` : voteText;
  body.append(who, meta);
  li.append(chip, body);
  if (seat.correct !== null) {
    const mark = document.createElement("span");
    mark.className = `badge ${seat.correct ? "correct" : "wrong"}`;
    mark.textContent = seat.correct ? "You got it" : "Fooled you";
    li.append(mark);
  }
  return li;
}

/* ----------------------------------------------------------------- wire */
$("join-group").addEventListener("click", joinGroup);
$("room-form").addEventListener("submit", sendRoomMessage);
$("vote-panel").addEventListener("submit", submitVote);
$("room-again").addEventListener("click", findRoom);
$("room-lobby").addEventListener("click", () => toLobby());
