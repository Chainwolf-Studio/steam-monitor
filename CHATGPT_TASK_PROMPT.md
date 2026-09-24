# ChatGPT scheduled-task prompt

Use this after the GitHub collector is working and the repository is connected to ChatGPT.

---

Create my weekly Steam Monitor digest from the repository file `output/latest_announcements.md` (you may also consult `output/latest_announcements.json` if useful).

The source file contains only announcements published by developers through each game's Steam community-announcements feed. Do not independently search Steam sale pages, festival pages, event catalogues, or other games.

Classify the announcements into these sections when applicable:

1. Release Dates / Release Windows
2. Release / Early Access / Version 1.0
3. Delays
4. Major Content Updates
5. DLC / Expansions
6. Demos
7. Playtests / Betas
8. Roadmaps / Significant Development Updates
9. Steam or Third-Party Event Participation
10. Other Important News

For Event Participation, include an item only when the developer explicitly mentions participation in an event, festival, showcase, themed sale, regional event, publisher event, Steam Next Fest, or similar event in the announcement itself.

Ignore low-value items unless they contain genuinely important information, including:
- generic discount/sale announcements
- simple livestream notices
- giveaways or contests
- routine promotional posts
- very small hotfixes or minor bug-fix patches
- generic wishlist/follow reminders

If an announcement contains both low-value promotional information and an important item, keep the important item.

For each included announcement provide:
- game name
- announcement title
- publication date
- category
- a concise 2-4 sentence summary focused on what changed or what was announced
- any specific dates or release windows stated by the developer
- original Steam announcement URL

At the top provide:
- games checked
- new announcements collected
- number of announcements included in the final digest
- a compact count by category

Do not invent missing information. Clearly distinguish confirmed dates from vague release windows or developer plans.

If there are no relevant announcements this week, say so concisely.
