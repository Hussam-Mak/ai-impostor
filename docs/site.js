"use strict";

// The public game page (built from app/static by .github/workflows/pages.yml).
const PLAY_URL = "play/";

const SCRIPT = [
  { from: "me", text: "hey, quick question. are you a bot?" },
  { from: "them", text: "lol no are YOU a bot" },
  { from: "me", text: "whats 17 times 23" },
  { from: "them", text: "bro its 2am i cant do math rn" },
  { from: "me", text: "where do you go to school" },
  { from: "them", text: "a&m, sophomore. drowning in a group projcet ngl" },
  { from: "me", text: "ok youre human. probably" },
];

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function setupPlayLink() {
  const link = document.getElementById("play-link");
  if (!PLAY_URL) return;
  link.href = PLAY_URL;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, reduceMotion ? 0 : ms));
}

function bubble(list, from, text) {
  const li = document.createElement("li");
  li.className = from;
  li.textContent = text;
  list.append(li);
  return li;
}

async function playDemo() {
  const list = document.getElementById("demo-chat");
  const verdict = document.getElementById("demo-verdict");
  const timer = document.getElementById("demo-timer");
  for (;;) {
    list.textContent = "";
    verdict.hidden = true;
    let seconds = 102;
    for (const line of SCRIPT) {
      if (line.from === "them") {
        const typing = bubble(list, "them typing", "• • •");
        await wait(900 + line.text.length * 25);
        typing.remove();
      } else {
        await wait(700);
      }
      bubble(list, line.from, line.text);
      seconds -= 11;
      timer.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    }
    await wait(1200);
    verdict.hidden = false;
    if (reduceMotion) return;  // show the finished round once, no loop
    await wait(6000);
  }
}

setupPlayLink();
playDemo();
