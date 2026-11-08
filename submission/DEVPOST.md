# Devpost submission: AI Impostor

Copy each section into the matching Devpost field. Items in **[brackets]** are for you to fill in.

---

## Project name

AI Impostor

## Tagline (one line)

Chat with strangers, then vote: who's human, and who's an LLM on Databricks pretending to be one?

## Try it out

- **Play (no sign-up):** https://hussam-mak.github.io/ai-impostor/play/
- **Project site:** https://hussam-mak.github.io/ai-impostor/
- **Code:** https://github.com/Hussam-Mak/ai-impostor
- **Databricks App version** (needs workspace access): https://ai-impostor-7474657692011817.aws.databricksapps.com

## Built with

`databricks` `databricks-apps` `model-serving` `foundation-model-apis` `llama-3.3` `unity-catalog` `delta-lake` `databricks-sql` `mlflow` `databricks-jobs` `databricks-asset-bundles` `python` `fastapi` `scikit-learn` `javascript` `github-pages` `render`

---

## Inspiration

Chatbots now write the way people text. We wanted to turn the Turing test into something you *play*, not read about, and to make every round produce data that answers real questions: how often do people get fooled, which kinds of "people" fool them, and can a model catch what humans miss?

## What it does

AI Impostor is a chat game with two modes:

- **1-on-1:** you're matched with a stranger for two minutes. It's either another player or an LLM playing one of four human personas: a sleep-deprived CS sophomore, a stressed stats PhD student, a skeptical engineer, a hype-machine freshman. Then you guess: human or AI?
- **Group chat:** 1–5 players join a room with 1–3 hidden AI impostors, everyone under a random alias. Nobody knows how many AIs there are. After three minutes everyone votes on each member, and the reveal shows who was who, what persona each AI played, and how everyone voted.

Scoring rewards catching AIs and, in group mode, also *seeming human* to the other players.

Every round is logged to Unity Catalog, and that data drives analytics plus an AI-message detector that competes against the players.

## How we built it

Everything that thinks or remembers runs on **Databricks**:

- **The impostor:** the Llama 3.3 70B chat endpoint through **Databricks Model Serving / Foundation Model APIs**. Each AI gets a persona with a backstory and a texting style, plus strict "sound human" rules. Replies are then post-processed: giveaway phrases are swapped for deflections, length is capped, lowercase and the occasional typo are added for some personas, and replies are delayed to mimic typing.
- **Group conversation:** the hard part. After each message, the server picks at most one AI that *may* reply. It's weighted toward whoever was just mentioned by name, and the AI that just spoke is never picked. The model can answer `PASS` to stay quiet, and if the room goes silent, an AI may break the ice. A bot that answers everything is easy to spot.
- **Data:** every 1-on-1 game, group room, message, seat and vote is written to **Unity Catalog Delta tables** through a **Databricks SQL warehouse**, using parameterized SQL. The app's identity has insert-only grants.
- **Analytics:** a notebook builds **Unity Catalog views**: detection accuracy, fool rate per persona, accuracy vs. chat length, AI vs. human writing style, crowd vs. one-on-one fool rate, and whether talking more gets an AI voted out.
- **ML:** a scikit-learn text classifier, tracked with **MLflow** and registered in the **Unity Catalog model registry**. It learns the "AI tells" from every message and is scored against human players on held-out games.
- **Ops:** one **Databricks Asset Bundle** deploys the app, the setup job and an hourly **Databricks Job** that refreshes the analytics and retrains the detector.
- **The game itself:** a FastAPI server with a no-build HTML/CSS/JS front end. It runs as a **Databricks App** for workspace users. For the public, the same page is on GitHub Pages and the same server runs on Render, still calling Databricks for the AI and the data.

## Challenges we ran into

- **Keeping the game fair.** Our first version had tells that had nothing to do with the chat. Human matches appeared instantly while AI matches took a few seconds. Only humans could end a chat early. In group mode, the number of seats revealed how many AIs there were. We fixed each one: every match waits the same random 3–9 seconds, the AI can "leave" early too, AI counts are random, and nobody sees answers until every vote is in.
- **Teaching an LLM group etiquette.** One-on-one, the AI just answers. In a group it has to decide *whether* to speak, *who* to answer, and when to stay quiet, without flooding the room or replying to itself.
- **Our AI was secretly a script.** For a while, every deployment quietly fell back to the offline scripted bot. One unsupported argument in the Databricks client setup was caught and silenced. Fittingly, our impostor was itself an impostor. A regression test now checks that call against the real SDK.
- **Public play vs. workspace login.** Databricks Apps require a workspace login, which judges and players don't have. We split hosting so anyone can play while all the AI and data stays on Databricks.
- **Running an LLM on the open internet.** We added an hourly cap on LLM calls (a scripted bot answers beyond it), per-visitor rate limits that can't be dodged with spoofed headers, message, room and player caps, and a watchdog for stuck AI turns.

## Accomplishments that we're proud of

- A Turing test that's actually fun, in two modes, playable by anyone from a link.
- An AI that holds a believable group conversation: it addresses people by name, deflects accusations and stays quiet sometimes.
- The full Databricks loop: game → Model Serving → Unity Catalog → analytics views → MLflow model → scheduled Job, deployed from one bundle.
- 94 automated tests, plus two independent code reviews (Python and security) whose findings we fixed.

## What we learned

- What makes an AI sound human is mostly *restraint*: short replies, not answering everything, vagueness, a typo. Not intelligence.
- Fairness in a Turing-test game is mostly about everything *except* the conversation: timing, how chats end, how many seats there are.
- Unity Catalog plus a SQL warehouse makes it easy to log from a live app and analyze in the same place, and the Asset Bundle kept the whole setup reproducible.

## What's next for AI Impostor

- **Show the model live:** serve the MLflow detector on a Model Serving endpoint, and after each guess show "Our model thought this stranger was 82% AI."
- **Publish an AI/BI dashboard** on the analytics views, and a Genie space to ask the game data questions.
- **Turn on MLflow tracing** for every impostor reply, so anyone can inspect the prompts behind a conversation.
- **More personas and models.** Run different Model Serving endpoints head to head and see which LLM is the best impostor.

## Results so far

**[After real players have played: run the `ai-impostor-insights` job and paste 2–3 numbers here, e.g. "Players spotted the AI X% of the time", "Most convincing persona: …", "The detector beat human players by N points."]**

## Use of AI tools

The project was built with Claude (Anthropic), via Claude Code, as a pair programmer: writing and reviewing code, tests and documentation. The in-game impostor runs on Llama 3.3 70B through Databricks Model Serving.

## Team

**[Your name(s), and what each person did]**
