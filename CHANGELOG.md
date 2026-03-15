# Changelog

## 0.1.0 (2026-03-15)


### Features

* agregar CodeRabbit config y Release Please workflow ([0629d8c](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/0629d8c5100b4dc651c5c2bcc029a50b9f023265))
* agregar Security Review automatico con Claude en cada PR ([7f7b839](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/7f7b8397789734c63b53c3e6b62efaf71ca927dd))
* email service con reporte diario y APScheduler ([9742825](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/97428251d79335c383ba7fa85bd2183c4810a737))
* first commit with tests and CI/CD ([3b76fd8](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/3b76fd806db6bffed8eb6a9b6f308a780ca22795))
* floating PO reminder with pair name + direction when opening PO ([1501141](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/1501141cbff2376a48cf4803b5abf292cb8d7a40))
* implementar Agent Teams Lite con 6 subagentes especializados ([f9c02e0](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/f9c02e0de8a62b693896fca95f49630b4694ee54))
* implementar consenso ortogonal en quality_score ([4863771](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/486377195c119263a7c19dcb8dcfe7623b416da0))
* implementar Skills Router con carga selectiva por tarea ([4fef29a](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/4fef29a36b9858350a9733a4839fd0de4ae96775))
* one-click PO redirect with asset pre-selected + demo/real toggle ([64f1843](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/64f1843511dee09b9949883a24d046c03033bf9e))
* persistencia visual W/L por par en localStorage ([b0e2be6](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/b0e2be6098de8727b31fb53c258300d557a08299))
* reemplazar KeltnerRSI por RangeBreakout anticorrelacionada ([76fb843](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/76fb8430985f6ab4ecae145633a845c2914c1f25))
* Sprint 1 - Persistencia MongoDB + cache Redis Win Rate ([c00a3d8](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/c00a3d849bc5e92615c6571bf65a6a96929963e9))
* Sprint 2 - CB autonomo, session labels, calibracion por par ([eb2ddfa](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/eb2ddfa98df6fa3c6b0a33ad19df1e525fbacea1))


### Bug Fixes

* add CCI momentum mode (&gt;=150) and Stoch extreme mode (&gt;=95) for signal generation ([51beb84](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/51beb84356549e2103178324e59d22f28a3b1b81))
* add Dockerfile to backend/ dir (compose context) + python healthcheck ([11471e2](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/11471e246714344ff840ccad26eb86aca3f66c6a))
* add tzdata for ZoneInfo America/Havana support in Docker slim ([94b595d](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/94b595d24d37e0e92378c1330e92d83810d5c476))
* agregar package-lock.json para que npm ci funcione en CI/CD ([393102d](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/393102d9567bc557fec33a995b7863191e7eb24a))
* assetId scope error in _showPOReminder + deduplicate signal log entries ([dfd5f47](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/dfd5f47e863c1c9944afa2b27cea20622b72e09c))
* calibration only uses high-confidence trades, raise min sample to 20 ([7793215](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/7793215adfc1881ebeabd4d93ee3ab229274f27f))
* clipboard copies euraud_otc format + reduce signal polling 30s-&gt;5s ([8fbc414](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/8fbc4141ddd63e454aec06ae5097ab1166143c9c))
* corregir 4 bugs criticos en scan manual de señales ([a22ac84](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/a22ac847922f0c2652cc875c021cbf7680f920a9))
* CORS headers in Nginx + timezone-aware clock (DST auto) ([926598d](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/926598dc8207063c2f1374411e91e536b6b12c72))
* OTC verifier false losses + PO WebSocket init in lifespan + import fix ([e5e3428](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/e5e3428a1893ec025fd0b8ee2923b87b83bbd08b))
* rehabilitar auditoria autonoma con precio de cierre real ([23e81cb](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/23e81cbbea323ae1dc44789314c05746177e18c4))
* remove duplicate WS protocol headers causing HTTP 400 ([6692ade](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/6692ade9279005b5377d48430ee088fc4396cf8f))
* remove zip files from git tracking ([bf47193](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/bf47193bcaefd6624b8b0ed60b360a1b121d397f))
* skip cookie on HTTP 400 (IP mismatch) - demo WS works without auth ([979e191](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/979e191a995251e9ace63970a89b4fd7bbf8edf7))
* usar onboarding@resend.dev como remitente (dominio verificado) ([1dd1f4b](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/1dd1f4b906086b89e41184174822f4e6a79c9ed8))
* use docker-compose legacy command for VPS compatibility ([4ef6d30](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/4ef6d301e6c8db2baec73a7da8e75f2383e64e88))
* use PO WebSocket price for audit verification (saves Twelve Data credits) ([c0352b0](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/c0352b0af3f677f998c24976581f4a537a4f29f2))
* use python healthcheck instead of curl (not available in container) ([3e66b7a](https://github.com/amustelierbeckles-bot/trading-bot-option/commit/3e66b7ab9cd1291f0f5b2543535781ec2c084ac1))
