# SensePlace 통합 Smoke Test
# 사용: .\scripts\smoke_test.ps1
# 3 서버(Django:8000, FastAPI:8001)가 실행 중이어야 합니다.

$ErrorActionPreference = "Stop"
$passed = 0
$failed = 0

function Test-Step($name, $script) {
    Write-Host -NoNewline "[ ] $name ... "
    try {
        & $script
        Write-Host "PASS" -ForegroundColor Green
        $script:passed++
        $global:passed++
    } catch {
        Write-Host "FAIL" -ForegroundColor Red
        Write-Host "  $_" -ForegroundColor DarkRed
        $global:failed++
    }
}

Write-Host "`n=== SensePlace Smoke Test ===`n"

# Django 헬스체크
Test-Step "Django 서버 응답" {
    $r = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/vocs/" -Method Get -ErrorAction Stop
    if (-not $r) { throw "응답 없음" }
}

# FastAPI 헬스체크
Test-Step "FastAPI 헬스체크" {
    $r = Invoke-RestMethod -Uri "http://localhost:8001/internal/v1/health" -Method Get -ErrorAction Stop
    if ($r.status -ne "healthy") { throw "상태: $($r.status)" }
    Write-Host -NoNewline "(provider=$($r.llm_provider)) "
}

# 로그인 (운영관리자)
$session = $null
Test-Step "로그인 (운영관리자)" {
    $body = @{ staff_id = "staff.ops"; password = "demo1234" } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login/" -Method Post -Body $body -ContentType "application/json" -SessionVariable s -ErrorAction Stop
    $script:session = $s
    if ($resp.error) { throw $resp.error.message }
}

# VOC 목록 조회 (인증 후)
Test-Step "VOC 목록 조회" {
    $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/vocs/" -Method Get -WebSession $script:session -ErrorAction Stop
    if ($resp.error) { throw $resp.error.message }
    $count = if ($resp.data) { $resp.data.Count } else { 0 }
    Write-Host -NoNewline "($count VOCs) "
}

# Job 생성
$jobId = $null
Test-Step "Job 생성 (detection)" {
    $body = @{ type = "detection"; payload = @{ scope = "all" } } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/jobs/" -Method Post -Body $body -ContentType "application/json" -WebSession $script:session -ErrorAction Stop
    if ($resp.error) { throw $resp.error.message }
    $script:jobId = $resp.data.job_id
    Write-Host -NoNewline "(job=$($script:jobId)) "
}

# FastAPI 내부 API
Test-Step "FastAPI 품질 게이트 API" {
    $body = @{ scope = "all" } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "http://localhost:8001/internal/v1/quality-gates" -Method Post -Body $body -ContentType "application/json" -ErrorAction Stop
    Write-Host -NoNewline "(status=$($resp.status)) "
}

# 결과
Write-Host "`n=== 결과 ==="
Write-Host "PASS: $passed"
Write-Host "FAIL: $failed"
if ($failed -gt 0) {
    Write-Host "`n일부 테스트 실패" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n모든 테스트 통과" -ForegroundColor Green
    exit 0
}
