# AI Impostor: demo video script

A recorded screen demo with voiceover. **Length: about 2.5 minutes.** One person, no skit.

## Before you hit record

1. **Wake the server:** open https://hussam-mak.github.io/ai-impostor/play/ and wait until the lobby loads fully, with the stats card filled in.
2. **Warm the warehouse:** in Databricks, open a SQL editor on **Serverless Starter Warehouse** and run `SELECT 1`.
3. **Open these tabs, in order:**
   1. Project site: https://hussam-mak.github.io/ai-impostor/
   2. Game: https://hussam-mak.github.io/ai-impostor/play/
   3. Databricks SQL editor with this query pasted (don't run it yet):
      ```sql
      -- Last 1-on-1 game: who said what, and which persona the AI played
      SELECT m.seq, m.sender_kind, g.persona, m.text
      FROM workspace.ai_impostor.messages AS m
      JOIN workspace.ai_impostor.games AS g USING (game_id)
      WHERE g.started_at = (SELECT MAX(started_at) FROM workspace.ai_impostor.games)
      ORDER BY m.seq;
      ```
      For the last group round instead:
      ```sql
      SELECT m.seq, m.alias, m.sender_kind, m.persona, m.text
      FROM workspace.ai_impostor.room_messages AS m
      JOIN workspace.ai_impostor.rooms AS r USING (room_id)
      WHERE r.started_at = (SELECT MAX(started_at) FROM workspace.ai_impostor.rooms)
      ORDER BY m.seq;
      ```
      A game is saved once its guess (1-on-1) or vote (group) is done, and can take a few seconds to show up.
   4. Databricks **Catalog Explorer** open at `workspace` → `ai_impostor`, showing the tables.
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

## Scene 5: The Databricks side (1:45–2:20)

**Screen:** Catalog Explorer showing the tables in `ai_impostor`.

**Voiceover:**
> Everything behind the game runs on Databricks. Every game, message and vote is saved live to **Unity Catalog** through a **SQL warehouse**.

**Screen:** switch to the SQL editor and run the query. The round you just played appears.

**Voiceover:**
> Here's the round I just played: every message, and which ones came from the AI.

**Screen:** stay on the results, or briefly show the notebooks folder and the MLflow experiment if you have them open.

**Voiceover:**
> From there, notebooks build analytics on which personas fool people most and whether the AI is harder to catch in a group. An **MLflow** model learns to spot AI messages and is scored against the players. The whole setup deploys with one **Databricks Asset Bundle**, and a scheduled **Databricks Job** retrains the model.

## Scene 6: Close (2:20–2:30)

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
