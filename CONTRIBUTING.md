# Contributing

[English](#english) · [中文](#中文)

---

## English

Thanks for helping grow the list!

### How to submit

- Easiest: open an issue with the [submit-video template](../../issues/new?template=submit-video.yml).
- Or send a PR: run `python scripts/add_entry.py` to add the entry interactively (it updates `data/videos.json` and creates `prompts/<slug>.md`).

### Rules

- **Every entry credits the creator and links the original post.** That's the whole point of the list.
- **Prompt text: only what the creator publicly shared.** If the post only describes the video, paste that description and mark `prompt_partial: true`. Don't paste private or leaked prompts.
- `README.md` and `README.zh-CN.md` are generated from `data/videos.json` — never edit them directly. Edit `data/videos.json`, then run `python scripts/build_readme.py`.
- Before pushing: `python scripts/validate.py && python scripts/build_readme.py --check` (CI runs the same).

### Entry format

- **slug**: `{author-handle-lowercase}-{last 6 digits of the status id}`, e.g. `imjustnewatai-168580`
- **model**: one of `fable-5.5`, `opus-5.5`, `gemini-4-argon`, `gpt-6-astra`, `seedance-2.5`, `minimax-h3`, `kling-4`, `grok-imagine` (propose new ones in your PR)
- **category**: one of `motion`, `explainer`, `3d-scenes`, `games-interactive`, `long-form`, `music-videos`; for text-to-video models also `cinematic`, `ads`, `anime`
- **tech_tags**: from `canvas, svg, threejs, glsl, gsap, css, webgl, web-audio, particles, pixel-art, playable, ai-image, physics`; for text-to-video models `ai-video, image-to-video, multi-shot, native-audio` (propose new ones in your PR)

---

## 中文

感谢你的贡献!

### 如何提交

- 最简单:用 [submit-video 模板](../../issues/new?template=submit-video.yml)开 issue。
- 或提 PR:运行 `python scripts/add_entry.py` 交互式添加(会更新 `data/videos.json` 并生成 `prompts/<slug>.md`)。

### 规则

- **每个条目必须署名作者并链接原帖。** 这是这个列表存在的意义。
- **prompt 只收录作者公开发布的内容。** 如果原帖只是描述了视频,把描述贴上并标记 `prompt_partial: true`。不要贴私有或泄露的 prompt。
- `README.md` 和 `README.zh-CN.md` 由 `data/videos.json` 生成——不要直接改。改 `data/videos.json` 后运行 `python scripts/build_readme.py`。
- 推送前:`python scripts/validate.py && python scripts/build_readme.py --check`(CI 会跑同样的检查)。
