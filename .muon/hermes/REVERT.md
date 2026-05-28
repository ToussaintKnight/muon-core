# MBTI Personality Framework — Revert Plan

## What was changed

Three SOUL.md files were updated with MBTI cognitive function personality descriptions:
- `~/.hermes/SOUL.md` → Pixie (ENTJ)
- `~/.hermes/profiles/sunny/SOUL.md` → Sunny (ESFJ)
- `~/.hermes/profiles/luna/SOUL.md` → Luna (INTP)

## Revert to v1 (pre-MBTI)

```bash
# Pixie
cp /Users/knight/muon-core/.muon/hermes/profiles/pixie/backups/SOUL.md.v1 /Users/knight/.hermes/SOUL.md

# Sunny
cp /Users/knight/muon-core/.muon/hermes/profiles/sunny/backups/SOUL.md.v1 /Users/knight/.hermes/profiles/sunny/SOUL.md

# Luna
cp /Users/knight/muon-core/.muon/hermes/profiles/luna/backups/SOUL.md.v1 /Users/knight/.hermes/profiles/luna/SOUL.md
```

## Partial revert (remove only MBTI section)

Edit each SOUL.md and delete everything from "## Personality Framework" to the "---" separator before "## Your Role". The rest of the file is functionally identical to v1.

## Rollback effects

- MBTI behavior descriptions removed; agents revert to their generic personality
- Prefix cache invalidated for next session (one-time cost, ~5k tokens)
- No config or data changes; SOUL.md only
