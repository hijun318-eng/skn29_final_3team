# DataHub v1.7 인증·접근 프로필 운영 가이드

## 적용 계약

- DataHub 이미지는 `v1.7.0`으로 고정한다.
- GMS와 Frontend 모두 `METADATA_SERVICE_AUTH_ENABLED=true`를 사용한다.
- GMS는 `AUTH_POLICIES_ENABLED=true`, `VIEW_AUTHORIZATION_ENABLED=true`,
  `REST_API_AUTHORIZATION_ENABLED=true`를 사용한다.
- 토큰 서명 키·salt·system client secret·PAT는 `.env` 또는 운영 비밀 저장소에서만
  주입한다. 저장소에는 환경 변수 이름만 둔다.
- 서버 접근 매핑의 단일 계약은
  `config/server-access-profiles.v1.json`이다.

DataHub v1.7.0의 `application.yaml`은 위 네 플래그와 health 인증 제외 경로를
정의한다. Metadata Service 인증 문서는 GMS와 Frontend에 인증을 함께 켜고,
프로그램 호출은 `Authorization: Bearer <PAT>`를 사용하도록 요구한다.

- 고정 소스: <https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-service/configuration/src/main/resources/application.yaml>
- 인증 문서: <https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/docs/authentication/introducing-metadata-service-authentication.md>

## 운영 적용 순서

1. `.env.example`의 `REQUIRED` 값을 복사하지 말고 각각 충분히 긴 무작위 값으로
   교체한다. 실제 값은 커밋하지 않는다.
2. DataHub에 `rooms`, `membership`, `food_and_beverage`, `facility`, `banquet` Domain을
   만들고 대상 Dataset을 정확한 Domain에 배치한다.
3. 다섯 `datahub_actor`를 생성한다. 광범위한 Reader/Admin 역할을 부여하지 않는다.
4. 각 actor에 대해 계약의 `database_grants`에서 `database_domains`로 파생한 Domain만 대상으로 다음 Metadata Policy 권한을
   명시적으로 허용한다.
   - `VIEW_ENTITY` (DataHub v1.7 UI의 **View Entity**)
5. 기본 `All Users` 정책에 의존하지 않는다. 특히 전역 View Entity Page 권한이
   남아 있으면 비활성화하거나 적용 대상에서 제외한다.
6. 각 actor 명의 PAT를 생성하고 계약의 `datahub_token_env`에 주입한다. ingestion과
   Semantic Catalog 게시 PAT는 별도 actor·환경 변수로 운용한다.
7. `infrastructure/database/scripts/verify-service-fragment.ps1`로 compose와 계약을
   검증한 뒤 기동한다.
8. 관리자 PAT를 커밋되지 않는 `DATAHUB_BOOTSTRAP_TOKEN`에 주입하고 다음 명령을
   순서대로 실행한다. 두 명령은 PAT 값을 출력하지 않는다.

   ```powershell
   python infrastructure/database/datahub/bootstrap_access_control.py bootstrap
   python infrastructure/database/datahub/bootstrap_access_control.py verify
   ```

   bootstrap은 접근 actor와 명시적 Domain 정책, Domain, `AI_SEARCH_ALLOWED` Tag,
   Serving View의 실제 원천 Domain 및 lineage를 동일 입력으로 반복 적용할 수 있다.
   verify는 다섯 profile PAT의 actor 일치 여부까지 fail-closed로 확인한다.

## 프로필 경계

프로필은 UI preset일 뿐이며 서버는 각 DB의 독립 `database_grants` 합집합으로
허용 Domain·DataHub 후보·Context URN을 계산한다. 필요한 원천 DB grant가 하나라도
없으면 Serving View와 source join을 허용하지 않는다. `/catalog/sources`도 profile PAT로
허용 DB만 조회하며 공용 token이나 로컬 목록으로 fallback하지 않는다.

| profile | 허용 DataHub Domain | DataHub actor | Trino principal |
|---|---|---|---|
| `pms_only` | `rooms` | `answervice_pms_only` | `answervice_pms_only` |
| `crm_only` | `membership` | `answervice_crm_only` | `answervice_crm_only` |
| `pms_crm` | `rooms`, `membership` | `answervice_pms_crm` | `answervice_pms_crm` |
| `integrated_revenue` | `rooms`, `membership`, `food_and_beverage` | `answervice_integrated_revenue` | `answervice_integrated_revenue` |
| `integrated_operations` | `rooms`, `membership`, `food_and_beverage`, `facility`, `banquet` | `answervice_integrated_operations` | `answervice_integrated_operations` |

DataHub actor는 표에서 각 이름 앞에 `urn:li:corpuser:`를 붙인 URN이다.

## 검증과 제한

인증 없는 `/health` 성공은 정상이다. `/health`는 DataHub가 공식적으로 인증에서
제외한 경로이므로 인증 적용 증거로 사용하지 않는다. 인증이 필요한 GMS API를
무토큰으로 호출했을 때 거부되고, 각 PAT로 허용 Domain의 entity 조회만 성공하는지
확인한다.

DataHub Core v1.7의 `VIEW_AUTHORIZATION_ENABLED`는 entity page 접근을 제한하지만
OSS 검색 결과 자체를 정책으로 완전히 필터링하지 않는다. 따라서 서버 검색은 반드시
계약의 `domains` 필터를 함께 적용하고, 검색 결과 URN도 같은 Domain 집합으로 다시
검증해야 한다. 이 제한 때문에 본 계약은 `default_effect=deny`와
`application_domain_filter_required`를 명시한다.
