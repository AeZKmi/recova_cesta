# Литература и обоснование решений

Как каждое решение в коде связано с источником. Источники 1–16 лежат в папке
`knowledge/Literature` проекта; 17–21 — внешние описания используемых моделей и программ.

**Что проверено.** Строки, помеченные ✔, сверены с текстом статьи (раздел или
аннотация указаны). Остальные привязки сделаны по аннотациям: перед тем как ссылаться
на них в тексте работы, найдите в статье конкретное место и укажите страницу.

## Решение → код → источник

| Решение | Где в коде | Источник |
|---|---|---|
| Пороги звёзд 60 / 75 / 91 и игровое поле с фишкой | `scoring.py`, `static/game.js` | [1] ✔ разд. 4.6 (LogoHra) |
| Ход фишки по полю зависит от оценки распознавания | `static/game.js` (`moveToken`) | [2] ✔ аннотация: оценка пересчитывается в число клеток |
| Модели без дообучения на детской речи ошибаются чаще; WER 15,10 % (MMS) и 16,33 % (Whisper Turbo) даже после дообучения | README, «Ограничения» | [1] ✔ аннотация |
| Модель, дообученная на детской речи, заметно точнее | README, «Ограничения» | [2] ✔ аннотация; [1] ✔; [17] |
| Упражнения от звука к слогу и слову | `data/words.json`, `static/game.js` (`buildList`) | [6] ✔ аннотация: инструменты для фонации, артикуляции звуков и понимания языка |
| Распознавание на уровне фонем для логопедии | `phonetics.py`, `asr.py` (`PhonemeRecognizer`) | [5] ✔ аннотация; [19], [20] |
| ASR проверяет, насколько попытка близка к целевому слову, а не транскрибирует свободную речь | `scoring.py` (`best_match`, `analyze`) | [4] ✔ аннотация; [8] ✔ разд. 1: ASR как «word verification tool» |
| Взрослый может исправить оценку; решение остаётся за логопедом | кнопки Uznať / Neuznať, `/api/attempts/{id}/override` | [4], [12], [8] |
| Панель логопеда: мониторинг прогресса, статистика по звукам | `static/therapist.*`, `db.stats()` | [12] ✔ аннотация: performance monitoring, feedback для логопеда; [6] |
| Только позитивная обратная связь, похвала, награды и персонаж | `static/game.js` (`PRAISE`, `REWARDS`, робот) | [13] ✔ аннотация; [16] ✔ аннотация: praise stickers, character interaction; [11] |
| Игровая форма повышает мотивацию к домашней практике | вся игра | [9] ✔ аннотация (Apraxia World); [10]; [11] |
| Персонаж-робот | `static/game.js`, `static/style.css` | [14]; [10] |
| Распознавание при нарушениях голоса и в шуме требует специальных решений | README, «Ограничения» | [7] ✔ аннотация |
| Сравнение моделей по нескольким метрикам, включая задержку | `tools/compare_models.py` | [1] ✔ (WER моделей); [4] ✔ (точность распознавателей) |
| Словацкий контекст и существующие решения | README, введение | [1], [2], [3] |
| Ребёнок сразу слушает свою запись | кнопка Ja в `static/game.js` (`playOwn`) | [15] ✔ разд. обзора приложений: «Record and Playback» — одна из оцениваемых функций, есть лишь у 11 % приложений (n = 11) и помогает логопеду давать обратную связь |
| Методика дальнейшего UX-тестирования (Double Diamond, персоны) | README, «Ограничения» → дальнейшая работа | [16] ✔ аннотация; [14]; [15] |

## Список литературы (STN ISO 690)

Источники из папки `knowledge/Literature`:

1. KOVÁČ, Juraj, ONDÁŠ, Stanislav, STAŠ, Ján, PLEVA, Matúš a KIKTOVÁ, Eva. Concepts and Approaches for Gamified Speech Therapy Applications in the Slovak Language. *Electronics*. 2026, roč. 15, č. 14, 3165. DOI 10.3390/electronics15143165.
2. ONDÁŠ, Stanislav, STAŠ, Ján a ŠEVC, Richard. Speech recognition as a supportive tool in the speech therapy game. In: *2024 34th International Conference Radioelektronika (RADIOELEKTRONIKA)*. IEEE, 2024. DOI 10.1109/RADIOELEKTRONIKA61599.2024.10524060.
3. ONDÁŠ, Stanislav, ČIŽMÁR, Anton, ŠIMČIKOVÁ, Lea a KOVÁČ, Juraj. Speech therapy applications based on speech technologies. In: *2023 33rd International Conference Radioelektronika (RADIOELEKTRONIKA)*. IEEE, 2023. DOI 10.1109/RADIOELEKTRONIKA57919.2023.10109062.
4. HAIR, Adam, BALLARD, Kirrie J., AHMED, Beena a GUTIERREZ-OSUNA, Ricardo. Evaluating Automatic Speech Recognition for Child Speech Therapy Applications. In: *ASSETS '19: The 21st International ACM SIGACCESS Conference on Computers and Accessibility*. Pittsburgh: ACM, 2019. [DOI doplniť]
5. GROSSINHO, André, GUIMARÃES, Isabel, MAGALHÃES, João a CAVACO, Sofia. Robust phoneme recognition for a speech therapy environment. [Rok a zborník doplniť – v PDF nie sú uvedené na prvej strane.]
6. SAZ, Oscar, YIN, Shou-Chun, LLEIDA, Eduardo, ROSE, Richard, VAQUERO, Carlos a RODRÍGUEZ, William R. Tools and Technologies for Computer-Aided Speech and Language Therapy. *Speech Communication*. 2009, roč. 51, č. 10, s. 948–967.
7. MUHAMMAD, Ghulam, MASUD, Mehedi, ALELAIWI, Abdulhameed, RAHMAN, Md. Abdur, KARIME, Ali, ALAMRI, Atif a HOSSAIN, M. Shamim. Spectro-temporal directional derivative based automatic speech recognition for a serious game scenario. *Multimedia Tools and Applications*. 2015, roč. 74, s. 5313–5327. DOI 10.1007/s11042-014-1973-7.
8. POMPILI, Anna et al. Evaluation and Extensions of an Automatic Speech Therapy Platform. In: QUARESMA, Paulo et al. (eds.). *Computational Processing of the Portuguese Language. PROPOR 2020*. Lecture Notes in Artificial Intelligence, zv. 12037. Cham: Springer, 2020, s. 43–52. DOI 10.1007/978-3-030-41505-1_5.
9. HAIR, Adam, AHMED, Beena, MARKOULLI, Constantina, MONROE, Penelope, McKECHNIE, Jacqueline, BALLARD, Kirrie J. a GUTIERREZ-OSUNA, Ricardo. Preliminary Results From a Longitudinal Study of a Tablet-Based Speech Therapy Game. In: *CHI 2020 Late-Breaking Work*. Honolulu: ACM, 2020.
10. NAVARRO-NEWBALL, Andrés A., LOAIZA, D., OVIEDO, C., CASTILLO, A., PORTILLA, A., LINARES, D. a ÁLVAREZ, G. Talking to Teo: Video game supported speech therapy. *Entertainment Computing*. 2014, roč. 5, s. 401–412.
11. SAEEDI, Soheila, BOURAGHI, Hamid, SEIFPANAHI, Mohammad-Sadegh a GHAZISAEEDI, Marjan. Application of Digital Games for Speech Therapy in Children: A Systematic Review of Features and Challenges. *Journal of Healthcare Engineering*. 2022, roč. 2022, 4814945. DOI 10.1155/2022/4814945.
12. POPOVICI, Doru-Vlad a BUICĂ-BELCIU, Cristian. Professional challenges in computer-assisted speech therapy. *Procedia – Social and Behavioral Sciences*. 2012, roč. 33, s. 518–522.
13. DUVAL, Jared, RUBIN, Zachary et al. Designing Towards Maximum Motivation and Engagement in an Interactive Speech Therapy Game. In: *IDC '17: Proceedings of the 2017 Conference on Interaction Design and Children*. Stanford: ACM, 2017. DOI 10.1145/3078072.3084329.
14. SHIN, Soomin, CHANDRA, Shruti, RAJAN, Archana, SHAH, Seema a DAUTENHAHN, Kerstin. How Co-design and Personas can Inform Game Implementation for Robot-assisted Speech Therapy in Clinical Settings. In: *2025 34th IEEE International Conference on Robot and Human Interactive Communication (RO-MAN)*. Eindhoven: IEEE, 2025. DOI 10.1109/RO-MAN63969.2025.11217571.
15. NAYAR, Revathy. Towards Designing Speech Technology Based Assistive Interfaces for Children's Speech Therapy. In: *ICMI '17: Proceedings of the 19th ACM International Conference on Multimodal Interaction*. Glasgow: ACM, 2017.
16. KIM, Sujin, KWON, Eunjin, YU, Jaesun, CHOI, Younggeun, KO, Myoung-Hwan, JO, Yun-ju, KIM, Hyun-Gi a YOU, Heecheon. User Experience Enhancement of a Gamified Speech Therapy Program Using the Double Diamond Design Framework. *Applied Sciences*. 2026, roč. 16, 826. DOI 10.3390/app16020826.

Используемые модели (внешние источники, не из папки Literature):

17. KInIT. *kinit/whisper-large-v3-sk* [model]. Hugging Face, 2025. Licencia Apache 2.0. Dostupné na: https://huggingface.co/kinit/whisper-large-v3-sk
18. RADFORD, Alec et al. Robust Speech Recognition via Large-Scale Weak Supervision. In: *Proceedings of the 40th International Conference on Machine Learning (ICML)*. 2023. (Whisper)
19. BAEVSKI, Alexei, ZHOU, Henry, MOHAMED, Abdelrahman a AULI, Michael. wav2vec 2.0: A Framework for Self-Supervised Learning of Speech Representations. In: *Advances in Neural Information Processing Systems 33 (NeurIPS 2020)*. 2020.
20. XU, Qiantong, BAEVSKI, Alexei a AULI, Michael. Simple and Effective Zero-shot Cross-lingual Phoneme Recognition. *arXiv:2109.11680*. 2021. (model *facebook/wav2vec2-xlsr-53-espeak-cv-ft*, https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft)
21. PRATAP, Vineel et al. Scaling Speech Technology to 1,000+ Languages. *Journal of Machine Learning Research*. 2024, roč. 25. (model *facebook/mms-1b-all*)

Источники 18–21 указаны по памяти: перед сдачей работы проверьте выходные данные
(особенно номер arXiv и том журнала). Год у [17] — год публикации модели в карточке;
уточните его там же.
