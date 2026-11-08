# AI Impostor: demo script

A 3-minute live demo built around a skit called **"The Human Who Failed the Turing Test."**
A 90-second solo version is at the end, for when you're presenting alone.

**Links**
- Play: https://hussam-mak.github.io/ai-impostor/play/
- Project site: https://hussam-mak.github.io/ai-impostor/
- Code: https://github.com/Hussam-Mak/ai-impostor

---

## Cast

| Role | Who | What they do |
| --- | --- | --- |
| **Host** | You | Runs the laptop on the projector, narrates |
| **The Plant** | A friend | Joins the group chat from their phone and plays the most robotic human ever |
| **Judges** | The audience | Vote on who the AI is |

## 10 minutes before you present

1. **Wake the server:** open https://hussam-mak.github.io/ai-impostor/play/ once. The free server sleeps after 15 idle minutes, and the first visit takes up to a minute.
2. **Warm the warehouse:** in Databricks, open a SQL editor tab on **Serverless Starter Warehouse** and run `SELECT 1`, so the live query in Act 3 is instant.
3. **Prepare the query tab.** Keep this ready (it shows the round you're about to play):
   ```sql
   SELECT r.started_at, m.alias, m.sender_kind, m.persona, m.text
   FROM workspace.ai_impostor.room_messages m
   JOIN workspace.ai_impostor.rooms r USING (room_id)
   ORDER BY r.started_at DESC, m.seq
   LIMIT 20;
   ```
4. **Brief The Plant:** they type like a malfunctioning robot (lines below). They must hit **Group chat** within ~5 seconds of you, so you land in the same room.
5. **Zoom the browser to 125–150%** so the back row can read the chat.

---

## Act 1: Cold open (0:00–0:25)

*Screen: the lobby. Host reads slowly, like a detective.*

> **HOST:** "*Yeah, PhD student in stats, you?*"
>
> That's a message from our game earlier today. Sounds like a person, right? Tired, a little vague, asks you a question back.
>
> It's not a person. It's Llama 3.3 running on Databricks Model Serving, and it's been told one thing: **don't get caught.**
>
> This is **AI Impostor**. You chat with strangers. Some of them are AIs pretending to be human. Then you vote.

## Act 2: The skit (0:25–1:50)

*Host clicks **Group chat**. The Plant hits **Group chat** on their phone at the same moment.*

> **HOST:** Group mode drops real players and hidden AIs into one chat. Everyone gets a random name. Nobody knows how many AIs there are, not even me.

*The room opens. Point at the member strip.*

> **HOST:** Five people. Some human, some not. Let's find out.

**Host types:** `ok everyone, prove you're human. what did you eat today?`

**The Plant types (deadpan, robotic), spread over the round:**
1. `GREETINGS. I AM A HUMAN. I CONSUMED FOOD TODAY.`
2. `I ENJOY HUMAN ACTIVITIES SUCH AS BREATHING.`
3. `beep. sorry. I mean: lol.`

*Read the AI replies out loud as they arrive. They'll be casual, lowercase, maybe a typo, maybe a jab at the Plant. React to them.*

> **HOST** *(to the audience)*: Notice what the AI does. Short messages. It doesn't answer everyone. It gossips. Sometimes it just... doesn't reply. That's on purpose: a bot that answers every message is easy to spot, so it's allowed to stay quiet.

*If an AI accuses the Plant of being a bot, milk it:*

> **HOST:** The AI is accusing the *human* of being the AI. It's running a campaign.

**Optional audience beat:** say the aliases out loud and ask the judges to point at who they think is the AI. Remember the answer.

*When the timer hits 0:00, the vote opens.*

> **HOST:** Judges, who's the impostor?

*Mark the Plant as **AI** (on purpose, it's the joke) and everyone else as you honestly think. Lock in. Then the Plant votes, and the reveal appears.*

## Act 2 payoff: The reveal (1:50–2:10)

*The reveal lists every member: human or AI, which persona each AI played, and how everyone voted.*

> **HOST:** The robot... was my friend. Fully human. Failed the Turing test.
>
> And the one that sounded like a sleepy grad student? *That* was the AI, playing a persona with a backstory: Houston, runs a lot, stressed about a paper.
>
> The AI doesn't need to be smart to fool you. It needs to be tired, a little bored, and make one typo.

*If the AI was caught, use this instead:* "Good catch. Our model is still learning, and so is everyone else. Which is where the data comes in."

## Act 3: It's all Databricks (2:10–2:50)

*Switch to the Databricks tab with the query ready. Run it.*

> **HOST:** Every word you just watched is already in **Unity Catalog**: the round, every message, who was human, who was AI, and every vote, written live through a **SQL warehouse**.

*Point at the rows from the round you just played.*

> **HOST:** And it's not just storage:
> - The impostor runs on **Databricks Model Serving**, through the Foundation Model APIs.
> - A notebook builds **analytics views**: which personas fool people most, and whether the AI is harder to catch in a crowd than one-on-one.
> - An **MLflow** model learns the "AI tells" from every message, gets registered in **Unity Catalog**, and competes against human players at spotting the impostor.
> - The whole thing deploys with one **Asset Bundle**, and a **Databricks Job** retrains the detector every hour.

## Close (2:50–3:00)

> **HOST:** So the question isn't "can AI pass as human?" It already does, sometimes. The question is **how often, which kinds, and can a model catch what we miss.** Every round you play answers it a little better.
>
> Scan, play, and see if you can catch it: **hussam-mak.github.io/ai-impostor**

---

## Solo version (90 seconds, no Plant)

1. **0:00** Cold open, same as Act 1.
2. **0:20** Click **1-on-1**. Ask the stranger 3 quick questions out loud and type them:
   - `be honest, are you a bot?`
   - `whats 17 times 23`
   - `what are you doing this weekend?`

   Read the replies. They'll dodge the math ("idk its late") and deflect the bot question.
3. **0:55** Ask the audience: human or AI? Click their answer. Read the reveal, including the persona backstory.
4. **1:10** Act 3, short: show the round in Unity Catalog, and name Model Serving, MLflow and the Asset Bundle.
5. **1:25** Close line.

## If something goes wrong

| Problem | Do this |
| --- | --- |
| "Waking up the game server…" | Talk through Act 1 slowly. It connects within a minute. This is why you wake it 10 minutes before. |
| The Plant ends up in a different room | Rooms start 6–10 s after the first person joins. Have them join right after you. If you still miss, play it as solo and let the Plant heckle from the audience. |
| AI replies are slow | Fill the gap: "It's typing on purpose. Instant replies are a dead giveaway." (They are delayed to mimic typing.) |
| The warehouse query is slow | It's cold-starting. Show the round's reveal screen instead and come back to the query. |
| Total failure | The project site has an animated example round: https://hussam-mak.github.io/ai-impostor/ |

## Judge Q&A cheat sheet

- **"How does the AI decide when to talk in a group?"** After each message the server picks at most one AI that may reply: more likely if it was just mentioned by name, never if it just spoke. The model can also answer `PASS` to stay quiet, and long silences let an AI break the ice.
- **"Can't you just ask it if it's an AI?"** It's prompted never to admit it. Its replies are post-processed: giveaway phrases are replaced with a deflection, length is capped, and typos and typing delays are added.
- **"Does wait time give it away?"** No. Every 1-on-1 match takes 3–9 seconds, human or AI, and both humans and the AI can end a chat early.
- **"What does it cost / how is it protected?"** An hourly cap on LLM calls (beyond it, a scripted bot answers), per-visitor rate limits, caps on messages, players and rooms, and insert-only table grants for the app.
- **"Why GitHub Pages and Render if it's a Databricks project?"** Databricks Apps require a workspace login, and we wanted anyone to be able to play. Pages hosts the page; a small Render server does matchmaking. **The AI, the data, the analytics and the ML all run on Databricks.** The full game also runs as a Databricks App for workspace users.
