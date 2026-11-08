# AI Impostor: demo video script

A recorded screen demo with voiceover. **Length: about 2 minutes 15 seconds.** One person, no skit.

## Before you hit record

1. **Wake the server:** open https://hussam-mak.github.io/ai-impostor/play/ and wait until the lobby loads fully, with the stats card filled in.
2. **Open these tabs, in order:**
   1. Project site: https://hussam-mak.github.io/ai-impostor/
   2. Game: https://hussam-mak.github.io/ai-impostor/play/
   3. Your group-chat table in Databricks Catalog Explorer (needs your Databricks login):
      https://dbc-788fee3e-1b59.cloud.databricks.com/explore/data/workspace/ai_impostor/room_messages?o=7474657692011817
      Click the **Sample Data** tab once so it's loaded. If it asks for a warehouse, pick **Serverless Starter Warehouse**.
3. **Play one round right before recording**, so the table shows a fresh game. A game is saved once its guess or vote is done.
4. **Zoom the browser to 125%** and close other tabs and notifications.
5. **Group chat scene:** have a friend ready on their phone. Without one, record only the 1-on-1 scene and skip Scene 4.

**Tip:** record each scene as a separate clip. Live AI replies vary, so redo a scene if a reply is flat, and trim the waits when editing.

---

## Scene 1: Hook (0:00–0:15)

**Screen:** the project site. Slowly scroll past the animated sample chat.

**Voiceover:**
> Chatbots now text like people. So we made the Turing test into a game. This is **AI Impostor**: you chat with strangers, some of them are AIs pretending to be human, and you have to figure out which.

## Scene 2: What it is (0:15–0:30)

**Screen:** switch to the game tab. Hover over the two mode buttons.

**Voiceover:**
> There are two modes. **1-on-1**: one stranger, two minutes, then you guess human or AI. And **Group chat**: a room of players with hidden AIs mixed in, and at the end everyone votes.

## Scene 3: Play 1-on-1 (0:30–1:15)

**Screen:** type a nickname, click **1-on-1**, wait for the match.

**Voiceover (during the wait):**
> Matching always takes a few random seconds, whether you get a person or an AI, so the wait doesn't give anything away.

**Type these, one at a time, and let the replies come in:**
1. `hey, quick question, are you a bot?`
2. `whats 17 times 23`
3. `what are you doing this weekend?`

**Voiceover (while replies arrive):**
> The AI is Llama 3.3, running on Databricks Model Serving. It plays a persona with a backstory and a texting style. Notice what it does: it won't do the math, it dodges the bot question, and it answers in short, lowercase messages. Replies are even delayed to look like typing.

**Screen:** click **I already know → guess now**, then pick **An AI**. Hold on the reveal for 2–3 seconds.

**Voiceover:**
> And the reveal: it was an AI, playing a stressed grad student from Houston. You get points for catching it, plus a streak bonus.

*(If you guessed wrong, say: "Fooled. It happens more than you'd think.")*

## Scene 4: Group chat (1:15–1:45)

**Screen:** click **Group chat**. Your friend joins on their phone right after. When the room opens, point the cursor at the member strip.

**Voiceover:**
> Group mode mixes real players with hidden AIs, all under random names. Nobody knows how many AIs are in the room.

**Type:** `ok everyone, prove you're human`, and let a few replies come in.

**Voiceover:**
> The AI has to act like a person in a group. It doesn't answer everything, it talks to people by name, and sometimes it accuses someone else of being the bot.

**Screen:** cut to the vote (skip the rest of the wait in editing). Mark everyone, lock in, and show the reveal list.

**Voiceover:**
> At the end you mark everyone human or AI, and the reveal shows who was who and how everyone voted.

## Scene 5: The Databricks side (1:45–2:05)

**Screen:** the `room_messages` table in Catalog Explorer, on the **Sample Data** tab. Slowly point the cursor at the `sender_kind` column (`human` / `ai`) and the `persona` column.

**Voiceover:**
> Everything behind the game runs on Databricks. The AI is Llama on **Databricks Model Serving**, and every message and vote is saved live to **Unity Catalog**. Here's a real group chat: you can see which lines came from the AI and which persona it was playing. **Notebooks** and an **MLflow** model then learn to spot the AI from this data, and the whole thing deploys with one **Databricks Asset Bundle**.

## Scene 6: Close (2:05–2:15)

**Screen:** back to the project site hero.

**Voiceover:**
> AI Impostor. Anyone can play from the link, no sign-up. See if you can catch the AI.

**On-screen text (last 3 seconds):**
`hussam-mak.github.io/ai-impostor`

---

## Recording checklist

- [ ] The server was woken up before recording (no "waking up" message on camera)
- [ ] Browser zoom at 125%, notifications off
- [ ] Each scene recorded as a separate clip; waits trimmed in editing
- [ ] No Databricks token or private settings visible on screen (don't open Render's Environment page while recording)
- [ ] Final video under the Devpost length limit (usually 3 minutes)
