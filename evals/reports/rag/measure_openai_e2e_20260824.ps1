param(
    [string]$BaseUrl = "http://127.0.0.1:28030",
    [string]$OutputPath = "$PSScriptRoot/performance_openai_daesung_remeasure_20260824.json",
    [string]$Username = $(if ($env:RAG_EVAL_USERNAME) { $env:RAG_EVAL_USERNAME } else { "analyst" }),
    [string]$Password = $env:RAG_EVAL_PASSWORD
)

$ErrorActionPreference = "Stop"
if (-not $Password) { throw "RAG_EVAL_PASSWORD is required" }
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$login = @{ username = $Username; password = $Password } | ConvertTo-Json
Invoke-RestMethod -Uri "$BaseUrl/auth/login" -Method Post -ContentType "application/json" -Body $login -WebSession $session | Out-Null

$cases = @(
    @{ question = "개인정보가 잘못 전달됐을 때 어떻게 해야 해?"; expected = @("02 개인정보") },
    @{ question = "보고서 작성 시 반드시 확인할 기준을 알려줘"; expected = @("03 보고서") },
    @{ question = "고객 불만을 접수한 뒤 처리 절차를 알려줘"; expected = @("06 고객응대", "15 고객의견") },
    @{ question = "객실에 문제가 생겼을 때 대응 절차를 알려줘"; expected = @("13 객실") },
    @{ question = "예약 불일치가 발생하면 어떻게 처리해?"; expected = @("09 입실 퇴실 예약 결제") },
    @{ question = "시설 고장이 발생하면 먼저 무엇을 해야 해?"; expected = @("11 시설") },
    @{ question = "안전사고 발생 시 대응 절차를 알려줘"; expected = @("14 안전") },
    @{ question = "예약 취소와 환불 기준을 알려줘"; expected = @("16 취소") }
)
$conversationIds = @(
    "b72b4251-ae6b-4032-b446-3daa45862487",
    "7cad55ee-68f1-4141-aece-81d498095767",
    "d46b89f7-0219-4e89-8662-ecc7502a8288",
    "797a1004-fea6-4dd5-93db-bddbb067af22",
    "beb7fc58-e426-4c7f-acb3-077541880788"
)

function Invoke-Rag([string]$Question, [string]$ConversationId = "") {
    $payload = @{ question = $Question; mode = "DOCUMENT_ONLY" }
    if ($ConversationId) { $payload.conversation_id = $ConversationId }
    $body = $payload | ConvertTo-Json
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-WebRequest -Uri "$BaseUrl/rag/query" -Method Post -ContentType "application/json" -Body $body -WebSession $session -TimeoutSec 30
    $timer.Stop()
    return @{ latency_ms = [Math]::Round($timer.Elapsed.TotalMilliseconds, 2); http = [int]$response.StatusCode; json = ($response.Content | ConvertFrom-Json) }
}

function Get-Percentile([double[]]$Values, [double]$Percentile) {
    $sorted = @($Values | Sort-Object)
    $position = ($sorted.Count - 1) * $Percentile
    $lower = [Math]::Floor($position)
    $upper = [Math]::Ceiling($position)
    if ($lower -eq $upper) { return [double]$sorted[$lower] }
    return [double]$sorted[$lower] + ($position - $lower) * ([double]$sorted[$upper] - [double]$sorted[$lower])
}

function Get-Documents($Data) {
    $documents = [Collections.Generic.List[string]]::new()
    foreach ($evidence in @($Data.evidence_bundle)) {
        if ($evidence.document_name -and -not $documents.Contains([string]$evidence.document_name)) {
            $documents.Add([string]$evidence.document_name)
        }
    }
    return @($documents)
}

1..3 | ForEach-Object { Invoke-Rag "안전사고 발생 시 대응 절차를 알려줘" | Out-Null }

$healthLatencies = @()
1..30 | ForEach-Object {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 10 | Out-Null
    $timer.Stop()
    $healthLatencies += $timer.Elapsed.TotalMilliseconds
}

$records = [Collections.Generic.List[object]]::new()
foreach ($repeat in 1..5) {
    foreach ($case in $cases) {
        $result = Invoke-Rag $case.question
        $data = $result.json.data
        $documents = @(Get-Documents $data)
        $hit = @($case.expected | Where-Object { $documents -contains $_ }).Count -gt 0
        $answer = [string]$data.answer.text
        $records.Add([ordered]@{
            kind = "single"
            repeat = $repeat
            question = $case.question
            expected_documents = @($case.expected)
            latency_ms = $result.latency_ms
            http = $result.http
            status = $data.status
            ranked_documents = $documents
            final_document_hit = $hit
            citations = @($data.citations).Count
            answer_characters = $answer.Length
            answer_text = $answer
            manual_semantic_review_required = $true
        })
    }
}

for ($index = 0; $index -lt 5; $index++) {
    $conversationId = $conversationIds[$index]
    $compare = Invoke-Rag "시설 문제와 안전사고 대응은 어떻게 달라?" $conversationId
    $compareData = $compare.json.data
    $compareDocuments = @(Get-Documents $compareData)
    $comparePass = ($compareDocuments -contains "11 시설") -and ($compareDocuments -contains "14 안전")
    $records.Add([ordered]@{
        kind = "compare"
        repeat = $index + 1
        question = "시설 문제와 안전사고 대응은 어떻게 달라?"
        latency_ms = $compare.latency_ms
        http = $compare.http
        status = $compareData.status
        ranked_documents = $compareDocuments
        context_pass = $comparePass
        citations = @($compareData.citations).Count
        answer_characters = ([string]$compareData.answer.text).Length
        answer_text = [string]$compareData.answer.text
        manual_semantic_review_required = $true
    })

    $followup = Invoke-Rag "즉시 보고 기준을 알려줘" $conversationId
    $followupData = $followup.json.data
    $followupDocuments = @(Get-Documents $followupData)
    $followupAnswer = [string]$followupData.answer.text
    $followupPass = ($followupDocuments -contains "11 시설") -and
        ($followupDocuments -contains "14 안전") -and
        ($followupAnswer -match "고립|인명") -and
        ($followupAnswer -match "화재|감전")
    $records.Add([ordered]@{
        kind = "followup"
        repeat = $index + 1
        question = "즉시 보고 기준을 알려줘"
        latency_ms = $followup.latency_ms
        http = $followup.http
        status = $followupData.status
        ranked_documents = $followupDocuments
        context_pass = $followupPass
        citations = @($followupData.citations).Count
        answer_characters = $followupAnswer.Length
        answer_text = $followupAnswer
        manual_semantic_review_required = $true
    })
}

$latencies = [double[]]@($records | ForEach-Object { $_.latency_ms })
$singles = @($records | Where-Object { $_.kind -eq "single" })
$comparisons = @($records | Where-Object { $_.kind -eq "compare" })
$followups = @($records | Where-Object { $_.kind -eq "followup" })
$elapsedSeconds = ($latencies | Measure-Object -Sum).Sum / 1000
$recordsJson = $records | ConvertTo-Json -Depth 12 -Compress
$sha = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($recordsJson))

$report = [ordered]@{
    measured_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    measurement_contract = "same OpenAI E2E question set as prior 2026-08-24 run"
    model = "OpenAI text-embedding-3-small"
    dimensions = 1024
    documents = 17
    chunks_vectors = 363
    mode = "DOCUMENT_ONLY warm-state sequential E2E"
    warmup_count = 3
    sample_count = $records.Count
    single_samples = $singles.Count
    success_rate = [Math]::Round(100 * @($records | Where-Object { $_.http -eq 200 -and $_.status -eq "ANSWER" }).Count / $records.Count, 2)
    citation_rate = [Math]::Round(100 * @($records | Where-Object { $_.citations -gt 0 }).Count / $records.Count, 2)
    single_document_hit_rate = [Math]::Round(100 * @($singles | Where-Object { $_.final_document_hit }).Count / $singles.Count, 2)
    comparison_context_pass = @($comparisons | Where-Object { $_.context_pass }).Count
    comparison_samples = $comparisons.Count
    followup_context_pass = @($followups | Where-Object { $_.context_pass }).Count
    followup_samples = $followups.Count
    semantic_completeness = "MANUAL_REVIEW_REQUIRED"
    latency_ms = [ordered]@{
        min = [Math]::Round(($latencies | Measure-Object -Minimum).Minimum, 2)
        mean = [Math]::Round(($latencies | Measure-Object -Average).Average, 2)
        p50 = [Math]::Round((Get-Percentile $latencies 0.50), 2)
        p95 = [Math]::Round((Get-Percentile $latencies 0.95), 2)
        p99 = [Math]::Round((Get-Percentile $latencies 0.99), 2)
        max = [Math]::Round(($latencies | Measure-Object -Maximum).Maximum, 2)
    }
    sequential_rps = [Math]::Round($records.Count / $elapsedSeconds, 3)
    health_ms = [ordered]@{
        mean = [Math]::Round(($healthLatencies | Measure-Object -Average).Average, 2)
        p95 = [Math]::Round((Get-Percentile ([double[]]$healthLatencies) 0.95), 2)
        max = [Math]::Round(($healthLatencies | Measure-Object -Maximum).Maximum, 2)
        samples = $healthLatencies.Count
    }
    records_sha256 = [Convert]::ToHexString($sha).ToLowerInvariant()
    records = $records
}

$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8
[ordered]@{
    measured_at = $report.measured_at
    sample_count = $report.sample_count
    success_rate = $report.success_rate
    citation_rate = $report.citation_rate
    single_document_hit_rate = $report.single_document_hit_rate
    comparison_context_pass = $report.comparison_context_pass
    followup_context_pass = $report.followup_context_pass
    latency_ms = $report.latency_ms
    sequential_rps = $report.sequential_rps
    health_ms = $report.health_ms
} | ConvertTo-Json -Depth 5
