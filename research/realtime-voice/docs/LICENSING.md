# Dependency and licensing audit

Read 2026-11-28 from the packages installed on `arm-free-1` (aarch64, Python 3.14.4)
and from each project's published licence. No claim below is inferred from a
package name alone.

## Components

| Component | Version | Licence | Commercial use | Notes |
| --- | --- | --- | --- | --- |
| pipecat-ai | 1.17.0 | BSD-2-Clause | Yes | Verified from repository LICENSE. Permissive, embeddable. |
| piper-tts | 1.8.0 | **GPL-3.0-or-later** | **Decision required** | Verified from `pip show` and the repo COPYING file. Copyleft. |
| onnxruntime | 1.32.0 | MIT | Yes | Piper inference backend. |
| audioop-lts | 0.2.2 | PSF-2.0 | Yes | Restores the G.711 codec removed from Python 3.13+. |
| numpy | installed | BSD-3-Clause | Yes | Resampling and framing. |
| websockets | installed | BSD-3-Clause | Yes | SignalWire stream transport. |
| pytest | installed | MIT | Yes | Tests only, not shipped. |

## The GPL question, stated plainly

`piper-tts` is GPL-3.0-or-later. If ApexVoice is proprietary, shipping Piper
inside the same process is the arrangement a lawyer should review. The options,
in ascending order of legal risk:

1. **Do not ship Piper.** Use a permissively licensed engine or a hosted voice.
   Costs money per call; no copyleft question.
2. **Isolate Piper behind a process boundary.** Run the `piper` binary as a
   separate program exchanging audio over a pipe or socket, which is the usual
   argument for keeping the GPL work separate from the proprietary host. This is
   still a legal judgement, not a settled fact.
3. **Accept GPL.** Only viable if ApexVoice's own terms are compatible.

The code here does not decide this. It records it, and the voice metadata carries
the dataset licence so the decision can be made with facts.

## Voice model licensing, which is the larger problem

Piper's own LICENSING.md (read 2026-11-28) says, in substance:

- The engine licence covers the **code**, not the voices.
- Piper makes **no grant** over voice models and adds no restriction of its own.
- A model card's `License` line describes **that voice's dataset only**.
- Whether trained weights are a derivative work of the corpus is **unsettled**, and
  Piper takes no position. Their guidance for commercial use is to take legal
  advice rather than treat a model card as permission.

### Voices assessed

| Voice | Language | Dataset | Dataset licence | Assessment |
| --- | --- | --- | --- | --- |
| `en_US-ljspeech-medium` | en_US | LJ Speech | **Public domain** | Lowest risk available in the catalogue. Used in this branch. |
| `fr_FR-siwis-medium` | fr_FR | SIWIS | **CC-BY 4.0** | Usable with attribution. Used in this branch. |
| `en_US-lessac-medium` | en_US | Blizzard 2013 | **Research licence** | **Do not ship commercially.** Widely copied in tutorials; the dataset is not commercial. |
| `fr_FR-upmc-medium` | fr_FR | UPMC Pierre | CC-BY-SA 4.0 | Share-alike; adds obligations to derived audio. Avoid unless needed. |

The module classifies each voice's dataset licence and refuses any voice whose
licence is unclassified or not commercially acceptable, so the tutorial default
(lessac) cannot be selected by accident. This is a guardrail, not legal advice.

## Practical recommendation

For a commercial ApexVoice V2:

- Treat the **Gemini Live in + local TTS out** combination as the cost play, but do
  not ship `piper-tts` in-process until the GPL question is settled. Running the
  `piper` binary out of process, or swapping in a permissive engine, keeps the
  option open.
- Ship **LJSpeech (public domain)** for English. It is the only common Piper voice
  whose dataset licence is unambiguously commercial.
- For French, CC-BY 4.0 (`siwis`) is usable **with attribution**; make sure the
  attribution appears somewhere real, not only in a repository.
- Avoid every voice trained on research corpora, including the popular lessac one.
