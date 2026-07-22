# Frontend workspace

호텔 VOC/운영 이슈 분석 Agent의 `React + Tremor` 프론트엔드 작업 공간입니다.

## Git 사용 원칙

- 이 폴더에서 만든 파일은 로컬에 먼저 저장됩니다.
- `git pull`은 파일을 원격에 업로드하지 않습니다.
- `git push`는 미커밋 파일이 아니라 commit된 변경만 원격에 업로드합니다.
- 공유할 준비가 되었을 때만 `git add frontend`, `git commit`, `git push origin minji` 순서로 반영합니다.
- `.env.local`, `node_modules/`, `dist/`, test coverage는 `.gitignore`로 제외합니다.

## 디렉터리 역할

```text
frontend/
├─ public/                 # 정적 파일
├─ src/
│  ├─ app/                # 앱 조립, route와 provider
│  ├─ assets/             # 이미지, font 등 source asset
│  ├─ components/
│  │  ├─ common/          # 공용 UI
│  │  └─ dashboard/       # 대시보드 전용 UI
│  ├─ features/           # 도메인 기능 단위 module
│  ├─ hooks/              # 공용 React hook
│  ├─ pages/              # route 단위 화면
│  ├─ services/           # API client와 외부 연동
│  ├─ styles/             # global style과 theme
│  ├─ test/               # test setup과 공용 fixture
│  └─ utils/              # framework 비종속 helper
└─ tests/                 # E2E test 자리
```

현재 단계에서는 팀이 package manager, React/Vite/Tremor version, API contract를 확정하기 전이므로 dependency와 build 설정은 만들지 않았습니다. 결정 후 이 구조 안에서 초기화합니다.

`src/main.jsx`, `src/app/App.jsx`, `src/pages/DashboardPage.jsx`, `src/services/apiClient.js`에는 구현 시작점을 마련했습니다. package와 build 설정은 version 결정 후 추가해야 실행할 수 있습니다.

## 로컬 환경변수

`.env.example`을 복사해 `.env.local`을 만들고 로컬 값만 입력합니다. `.env.local`은 commit하지 않습니다. 브라우저에 포함되는 환경변수에는 secret을 저장하지 않습니다.
