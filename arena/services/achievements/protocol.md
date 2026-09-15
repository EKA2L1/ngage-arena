# Achievements protocol

`AchievementService` accepts native XML `player` reports and commits before returning HTTP 200 with a body beginning `OK`. Up to 34 entries are allowed per native batch. The common database key is `(game_class, user_id, achievement_id)`; retries preserve the first earned time. Points and NGPType come from registered game definitions, never client-supplied totals.

Hooked declares 37 achievements totalling 1000 points: IDs 1–34 are solo; 35–37 multiplayer. IDs 35 and 36 correspond to Arena login (10) and first update (20). Game UID mappings join Launcher history to that same journal. Fresh databases store the native NGP category with each earned achievement.

Authorization follows ranking writes. Client reports establish reported unlocks, not server-side gameplay proof.
