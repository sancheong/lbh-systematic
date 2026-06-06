# Scripts

이 폴더의 스크립트는 LBH 자체 개발과 검증을 돕기 위한 보조 도구입니다.

## `scripts/create_demo_repo.py`

작은 샘플 프로젝트를 생성합니다.

```bash
python scripts/create_demo_repo.py /tmp/lbh-demo
```

생성되는 구조:

```text
/tmp/lbh-demo/
  src/payments/checkout.py
  src/notifications/bus.py
  tests/test_checkout.py
  pyproject.toml
```

용도:

- `lbh init`, `lbh index`, `lbh ask` 흐름을 빠르게 확인
- 검색 ranking이 결제/알림 파일을 찾는지 smoke test
- 새로운 기능을 붙인 뒤 수동 검증

## `scripts/run_tests.sh`

테스트 실행용 래퍼입니다.

```bash
scripts/run_tests.sh
```

내부적으로는 아래와 같습니다.

```bash
python -m pytest
```

## `scripts/package.sh`

프로젝트 전체를 배포용 zip으로 묶습니다.

```bash
scripts/package.sh
```

생성물:

```text
dist/lbh-systematic.zip
```

제외되는 항목:

- `__pycache__`
- `.pytest_cache`
- `.lbh`
- `dist`
- `build`
- `.git`

## 스크립트 추가 규칙

새 스크립트를 추가할 때는 다음을 지키세요.

1. 스크립트 상단에 사용법을 적습니다.
2. destructive action은 기본적으로 dry-run으로 둡니다.
3. repo root 밖 파일을 건드리지 않게 합니다.
4. 이 문서에 설명을 추가합니다.
