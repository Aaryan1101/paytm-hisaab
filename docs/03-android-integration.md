# Android integration guide (Kotlin + Jetpack Compose)

How the merchant app (Ramesh / Neha) talks to the backend: setup, networking, models, every screen's API calls, the camera
and voice flows, and the Soundbox mode. Endpoint details and full JSON examples are in the
[API reference](02-web-integration.md#part-2-api-reference-all-endpoints); this guide shows how to use them from Android.

Prerequisite: the backend is running ([setup guide](01-backend-setup.md)).

## 1. Dependencies

```kotlin
// build.gradle.kts (app)
plugins { kotlin("plugin.serialization") }

dependencies {
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-kotlinx-serialization:2.11.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    implementation("androidx.camera:camera-camera2:1.3.4")     // bill scanning
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("androidx.camera:camera-view:1.3.4")
    implementation("androidx.media3:media3-exoplayer:1.4.1")   // play the spoken replies
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
```

Permissions (`AndroidManifest.xml`): `INTERNET`, `CAMERA`, `RECORD_AUDIO`. Request camera and microphone at runtime.

## 2. Reaching the backend

| Where the app runs | Base URL | Notes |
|---|---|---|
| Emulator | `http://10.0.2.2:8000/` | `10.0.2.2` is the emulator's alias for your laptop |
| Phone on USB | `http://localhost:8000/` | run `adb reverse tcp:8000 tcp:8000` once |
| Phone on Wi-Fi | `http://<laptop-LAN-IP>:8000/` | same network, firewall open; start the server with `--host 0.0.0.0` |
| Demo / stage | `https://<tunnel>.trycloudflare.com/` | a tunnel is easiest; see the setup guide §9 |

Plain `http://` is blocked on Android 9+. For debug builds only, allow it:

```xml
<!-- res/xml/network_security_config.xml -->
<network-security-config>
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="true">10.0.2.2</domain>
    <domain includeSubdomains="true">localhost</domain>
  </domain-config>
</network-security-config>
<!-- AndroidManifest: <application android:networkSecurityConfig="@xml/network_security_config" ...> -->
```

**Spoken replies:** the backend builds `audio_url` from its `PUBLIC_BASE_URL` setting. That value must be an address *the
phone* can reach, otherwise the audio will not load. Set `PUBLIC_BASE_URL` to the same base URL you use above (or, if you
cannot, replace the host of `audio_url` with your own base URL on the client).

**Never** put the Sarvam key in the app. The app only knows the backend URL; there is no login.

## 3. Retrofit setup

Bill reading can take several seconds (the server waits on a Document AI job, up to 90 s), so give the client long timeouts.

```kotlin
@OptIn(ExperimentalSerializationApi::class)
val json = Json {
    namingStrategy = JsonNamingStrategy.SnakeCase   // so Kotlin camelCase maps to the API's snake_case
    ignoreUnknownKeys = true                        // the backend may add fields
    explicitNulls = false
}

val okHttp = OkHttpClient.Builder()
    .connectTimeout(10, TimeUnit.SECONDS)
    .readTimeout(120, TimeUnit.SECONDS)             // /invoices/ingest can be slow
    .writeTimeout(60, TimeUnit.SECONDS)
    .addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC })
    .build()

val api: HisaabApi = Retrofit.Builder()
    .baseUrl(BuildConfig.API_BASE_URL)              // must end with "/"
    .client(okHttp)
    .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
    .build()
    .create(HisaabApi::class.java)
```

### Error handling

Business errors come back as `{"error":"not_found","message":"…"}` with a 4xx status; request-validation errors use
`{"detail":[{"msg":"…"}]}`. Parse both:

```kotlin
@Serializable data class ApiErrorBody(val error: String? = null, val message: String? = null, val detail: List<Detail>? = null) {
    @Serializable data class Detail(val msg: String = "")
}

class ApiException(val status: Int, val code: String, override val message: String) : Exception(message)

suspend fun <T> call(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (e: HttpException) {
    val body = e.response()?.errorBody()?.string()?.let { runCatching { json.decodeFromString<ApiErrorBody>(it) }.getOrNull() }
    Result.failure(ApiException(e.code(), body?.error ?: "validation", body?.message ?: body?.detail?.firstOrNull()?.msg ?: e.message()))
} catch (e: IOException) {
    Result.failure(ApiException(0, "offline", "Network error"))
}
```

Codes worth special UI: `consent_required` (open the consent screen), `unreadable` ("retake the photo"), `not_applicable`
(hide the IMS tab), `invalid` (show `message`), `offline`.

## 4. Models

```kotlin
@Serializable data class Merchant(val id: Int, val name: String, val role: String, val gstScheme: String, val language: String)

@Serializable data class ForecastDay(val day: String, val inflow: Double, val outflow: Double, val balance: Double, val low: Double, val high: Double)

@Serializable data class Home(
    val merchant: Merchant, val oweThisWeek: Double, val suppliersDueThisWeek: Int, val alertCount: Int, val score: Int,
    val shortfallDate: String? = null, val shortfallAmount: Double = 0.0, val forecast: List<ForecastDay>,
)

@Serializable data class DueItem(val supplierId: Int, val supplierName: String, val amount: Double, val nextDue: String, val invoiceNos: List<String>)
@Serializable data class Dues(val period: String, val total: Double, val items: List<DueItem>)

@Serializable data class SupplierSummary(val id: Int, val name: String, val balanceDue: Double, val nextDue: String? = null, val risk: String, val gstinStatus: String)
@Serializable data class LedgerEntry(val day: String, val kind: String, val ref: String, val amount: Double, val balance: Double, val status: String? = null)
@Serializable data class Alert(
    val id: Int, val type: String, val severity: String, val messageEn: String, val messageHi: String,
    val invoiceId: Int? = null, val supplierId: Int? = null, val paymentId: Int? = null, val status: String,
)
@Serializable data class Ledger(val supplierId: Int, val supplierName: String, val balanceDue: Double, val entries: List<LedgerEntry>, val openIssues: List<Alert>)

@Serializable data class LineItem(
    val description: String, val hsn: String? = null, val qty: Double? = null, val unit: String? = null, val rate: Double? = null,
    val taxableValue: Double, val gstRate: Double? = null, val cgst: Double = 0.0, val sgst: Double = 0.0, val igst: Double = 0.0,
)
@Serializable data class Invoice(
    val supplierName: String, val supplierGstin: String? = null, val buyerGstin: String? = null, val invoiceNo: String,
    val invoiceDate: String, val dueDate: String? = null, val lineItems: List<LineItem>, val taxableTotal: Double,
    val taxTotal: Double, val roundOff: Double = 0.0, val grandTotal: Double, val billType: String,
)
@Serializable data class Issue(val code: String, val severity: String, val messageEn: String, val messageHi: String, val field: String? = null, val lineIndex: Int? = null)
@Serializable data class Duplicate(val invoiceId: Int, val invoiceNo: String, val invoiceDate: String, val paidOn: String? = null)
@Serializable data class Ingest(
    val invoiceId: Int, val invoice: Invoice, val issues: List<Issue>, val fieldConfidence: Map<String, Double>,
    val lowConfidenceFields: List<String>, val duplicate: Duplicate? = null, val imageUrl: String? = null,
)
@Serializable data class InvoiceState(val id: Int, val invoiceNo: String, val status: String, val confirmed: Boolean, val grandTotal: Double, val amountSettled: Double)

@Serializable data class Forecast(val buffer: Double, val firstBelowDate: String? = null, val shortfallDate: String? = null, val shortfallAmount: Double, val days: List<ForecastDay>)
@Serializable data class Reason(val factor: String, val positive: Boolean, val textEn: String, val textHi: String)
@Serializable data class Score(val score: Int, val factors: Map<String, Double>, val reasons: List<Reason>)
@Serializable data class CreditOffer(
    val eligible: Boolean, val reason: String, val offerId: Int? = null, val limit: Double = 0.0, val rateAprMin: Double = 0.0,
    val rateAprMax: Double = 0.0, val tenureDays: Int = 0, val reasons: List<String> = emptyList(), val illustrative: Boolean = true,
)
@Serializable data class Draft(val id: Int, val supplierId: Int, val amount: Double, val source: String, val status: String, val upiLink: String? = null)
@Serializable data class PaymentRecord(val id: Int, val amount: Double, val mode: String, val paidAt: String, val confirmed: Boolean, val supplierId: Int? = null)

@Serializable data class ToolCall(val name: String, val arguments: JsonObject, val result: JsonObject)
@Serializable data class ChatOut(val text: String, val toolCalls: List<ToolCall>, val source: String)
@Serializable data class VoiceOut(val transcript: String, val languageCode: String, val text: String, val audioUrl: String? = null, val toolCalls: List<ToolCall>, val source: String)
@Serializable data class Event(val id: Int, val text: String)
```

```kotlin
// IMS (regular-GST merchants only) and a few small responses
@Serializable data class ImsEntry(
    val id: Int, val supplierName: String, val invoiceNo: String, val invoiceDate: String, val taxable: Double, val tax: Double,
    val action: String? = null, val reasonEn: String? = null, val reasonHi: String? = null, val itcRisk: Boolean = false, val approved: Boolean = false,
)
@Serializable data class ImsMissing(val invoiceId: Int, val invoiceNo: String, val reasonEn: String, val reasonHi: String)
@Serializable data class Ims(val month: String, val counts: Map<String, Int>, val entries: List<ImsEntry>, val missingFromIms: List<ImsMissing>)
@Serializable data class ApproveAllOut(val approved: Int, val note: String)
@Serializable data class Consent(val id: Int, val scope: List<String>, val grantedAt: String, val expiresAt: String)
@Serializable data class QueryOut(val id: Int, val status: String, val invoiceId: Int, val answer: String? = null)

// Request bodies (field names become snake_case on the wire via the naming strategy)
@Serializable data class MerchantBody(val merchantId: Int)
@Serializable data class DraftIn(val merchantId: Int, val supplierId: Int, val amount: Double, val source: String = "bank")
@Serializable data class CashIn(val merchantId: Int, val supplierId: Int, val amount: Double)
@Serializable data class ConsentIn(val scope: List<String>)
@Serializable data class ConfirmIn(val corrections: JsonObject? = null)
@Serializable data class ConfirmPayeeIn(val supplierId: Int)
@Serializable data class OverrideIn(val action: String)             // accept | reject | pending
@Serializable data class ChatIn(val merchantId: Int, val text: String, val channel: String = "app", val language: String? = null)
```

## 5. The API interface

```kotlin
interface HisaabApi {
    @GET("merchants") suspend fun merchants(): List<Merchant>
    @GET("merchants/{id}/home") suspend fun home(@Path("id") id: Int): Home
    @GET("merchants/{id}/dues") suspend fun dues(@Path("id") id: Int, @Query("period") period: String = "week"): Dues
    @GET("merchants/{id}/suppliers") suspend fun suppliers(@Path("id") id: Int): List<SupplierSummary>
    @GET("merchants/{id}/suppliers/{sid}/ledger") suspend fun ledger(@Path("id") id: Int, @Path("sid") sid: Int): Ledger
    @GET("merchants/{id}/alerts") suspend fun alerts(@Path("id") id: Int, @Query("type") type: String? = null): List<Alert>
    @POST("merchants/{id}/alerts/{aid}/resolve") suspend fun resolveAlert(@Path("id") id: Int, @Path("aid") aid: Int): Alert
    @POST("merchants/{id}/payments/{pid}/confirm-payee") suspend fun confirmPayee(@Path("id") id: Int, @Path("pid") pid: Int, @Body body: ConfirmPayeeIn)

    @Multipart @POST("invoices/ingest")
    suspend fun ingest(@Part("merchant_id") merchantId: RequestBody, @Part("source") source: RequestBody, @Part file: MultipartBody.Part): Ingest
    @POST("invoices/{iid}/confirm") suspend fun confirmInvoice(@Path("iid") iid: Int, @Query("merchant_id") merchantId: Int, @Body body: ConfirmIn = ConfirmIn()): InvoiceState
    @POST("invoices/{iid}/discard") suspend fun discardInvoice(@Path("iid") iid: Int, @Query("merchant_id") merchantId: Int): InvoiceState
    @POST("invoices/{iid}/ask-supplier") suspend fun askSupplier(@Path("iid") iid: Int, @Query("merchant_id") merchantId: Int): QueryOut

    @GET("merchants/{id}/forecast") suspend fun forecast(@Path("id") id: Int, @Query("days") days: Int = 14): Forecast
    @GET("merchants/{id}/score") suspend fun score(@Path("id") id: Int): Score
    @POST("merchants/{id}/consents") suspend fun consent(@Path("id") id: Int, @Body body: ConsentIn): Consent
    @GET("merchants/{id}/credit-offer") suspend fun creditOffer(@Path("id") id: Int): CreditOffer
    @POST("merchants/{id}/credit-offer/{oid}/accept") suspend fun acceptOffer(@Path("id") id: Int, @Path("oid") oid: Int): CreditOffer

    @POST("payments/draft") suspend fun draftPayment(@Body body: DraftIn): Draft
    @POST("payments/{did}/confirm") suspend fun confirmPayment(@Path("did") did: Int, @Body body: MerchantBody): PaymentRecord
    @POST("payments/cash") suspend fun logCash(@Body body: CashIn): PaymentRecord
    @POST("payments/cash/{pid}/confirm") suspend fun confirmCash(@Path("pid") pid: Int, @Body body: MerchantBody): PaymentRecord
    @DELETE("payments/cash/{pid}") suspend fun cancelCash(@Path("pid") pid: Int, @Query("merchant_id") merchantId: Int)

    @GET("merchants/{id}/ims") suspend fun ims(@Path("id") id: Int, @Query("month") month: String): Ims
    @POST("merchants/{id}/ims/approve-all") suspend fun approveAllIms(@Path("id") id: Int, @Query("month") month: String): ApproveAllOut
    @POST("merchants/{id}/ims/{eid}/override") suspend fun overrideIms(@Path("id") id: Int, @Path("eid") eid: Int, @Body body: OverrideIn)

    @POST("agent/chat") suspend fun chat(@Body body: ChatIn): ChatOut
    @Multipart @POST("agent/voice")
    suspend fun voice(@Part("merchant_id") merchantId: RequestBody, @Part file: MultipartBody.Part): VoiceOut
    @GET("merchants/{id}/events") suspend fun events(@Path("id") id: Int, @Query("after_id") afterId: Int = 0): List<Event>

    @Streaming @GET("merchants/{id}/register.csv") suspend fun register(@Path("id") id: Int, @Query("month") month: String): ResponseBody
}
```

`merchantId` is a plain `Int` kept in app state (see §12). Prefer generating the client from `shared/openapi.json`
(`make openapi`) if your team uses OpenAPI Generator; this file is the hand-written equivalent.

## 6. Screens → API calls

| Screen | Calls | UI notes |
|---|---|---|
| **Home** | `home(id)` (one call) | "This week you owe **₹1,12,400** to **5** suppliers", the `forecast` line chart with the `low`/`high` band shaded, shortfall banner when `shortfallDate != null`, alert count, score |
| **Scan → Review** | `ingest(...)`, then `confirmInvoice` / `discardInvoice` / `askSupplier` | See §7 |
| **Suppliers** | `suppliers(id)` | Sorted by next due date. Badge from `risk` (`high` red, `medium` amber). Search is client-side |
| **Supplier ledger** | `ledger(id, sid)` | Timeline from `entries` (bills +, payments/credit notes −) with running `balance`. Buttons: Pay (§9), Request credit note (via `chat`), Call |
| **Alerts** | `alerts(id)`, `resolveAlert`, `confirmPayee` | One line per alert (`messageEn`/`messageHi`). `confirm_payee` alerts get a Confirm button → `confirmPayee(id, alert.paymentId, ConfirmPayeeIn(alert.supplierId))` |
| **IMS** (only if `gstScheme == "regular"`) | `ims(id, "2026-10")`, `overrideIms`, `approveAllIms` | Row shows suggested Accept / Reject / Pending and the reason. After "Approve all", show the returned note: it saves in Hisaab only |
| **Cash & credit** | `forecast`, `score`, then consent → `creditOffer` → `acceptOffer` | See §10 |
| **Soundbox mode** | `voice`, `events` | See §11 |
| **CA export** | `register(id, month)` | Save the CSV and share it with an intent |

Treat `creditOffer` returning `eligible = false` (HTTP 200) as a normal state: show `reason`.

## 7. Bill scanning

1. **Capture** with CameraX `ImageCapture` to a cache file:
   ```kotlin
   imageCapture.takePicture(
       ImageCapture.OutputFileOptions.Builder(file).build(), executor,
       object : ImageCapture.OnImageSavedCallback {
           override fun onImageSaved(r: ImageCapture.OutputFileResults) { upload(file) }
           override fun onError(e: ImageCaptureException) { /* show error */ }
       })
   ```
   Don't resize or rotate yourself; the server fixes EXIF rotation, caps the size and boosts contrast. Keep the file under
   15 MB (JPEG quality 85 is plenty).
2. **Upload** (show a progress indicator; it can take several seconds):
   ```kotlin
   suspend fun ingest(merchantId: Int, file: File): Result<Ingest> = call {
       val text = "text/plain".toMediaType()
       api.ingest(
           merchantId.toString().toRequestBody(text), "app".toRequestBody(text),
           MultipartBody.Part.createFormData("file", file.name, file.asRequestBody("image/jpeg".toMediaType())),
       )
   }
   ```
3. **Review screen** from the response:
   - Show `invoice` fields in editable inputs. **Highlight each name in `lowConfidenceFields`** (the server is unsure) and show a
     one-line explanation for each `issues` entry; for an issue with `lineIndex`, highlight that line item.
   - If `duplicate != null`, lead with it: *"This bill was already filed on 12 Oct and paid on 12 Oct"* and offer three buttons:
     **Duplicate, ignore** → `discardInvoice`; **It's a new bill** → `confirmInvoice`; **Ask supplier** → `askSupplier`.
   - Otherwise the buttons are **Confirm** (send edits as `corrections`) and **Discard**.
   - Correctable fields: `invoice_no`, `invoice_date`, `due_date`, `grand_total`, `taxable_total`, `tax_total`.
     Send only what changed: `ConfirmIn(corrections = buildJsonObject { put("grand_total", 18000) })`.
4. `422 unreadable` → "Couldn't read that bill. Please retake with the whole page in view."

The photo is **not** retrievable from the server later (`imageUrl` is private). Keep your own copy if the UI needs to show it.

## 8. Conversational assistant (text)

```kotlin
val reply = api.chat(ChatIn(merchantId, "Sharma ka hisaab", channel = "app")).getOrThrow()
// reply.text -> chat bubble;  reply.toolCalls[i].result -> structured data for rich cards
```

- The server remembers the conversation per merchant and channel (even across restarts), so send only the new message.
- If a tool result contains `status == "needs_confirmation"` with `pending_payment_id` (cash entry) or `draft_id` (payment),
  show **Confirm / Cancel** buttons and call `confirmCash` / `cancelCash` or `confirmPayment`. **The assistant cannot move
  money by itself.**

## 9. Paying a supplier

```kotlin
val draft = api.draftPayment(DraftIn(merchantId, supplierId, amount = 42300.0, source = "bank"))   // nothing moves yet
// Show "Pay ₹42,300 to Sharma Traders?"; on confirm:
startActivity(Intent.createChooser(Intent(Intent.ACTION_VIEW, Uri.parse(draft.upiLink)), "Pay with"))
// When the UPI app returns success (or immediately, for the mock demo):
api.confirmPayment(draft.id, MerchantBody(merchantId))
```

`source = "credit"` pays from an accepted credit offer; the backend refuses if it would exceed the limit (`422 invalid`).

## 10. Cash & credit flow (S5)

1. Show the forecast chart and the shortfall: *"Thursday you may be ₹38,000 short."*
2. **See credit option** → if `creditOffer` fails with `consent_required`, show the consent screen listing what is shared
   (GST data, bank data, valid 30 days). On **Agree**: `consent(id, ConsentIn(listOf("gst_data","bank_data")))`, then call
   `creditOffer` again.
3. Show the offer: limit, `rateAprMin`-`rateAprMax` labelled **illustrative**, `tenureDays`, and the `reasons` (score reasons).
4. **Accept** → `acceptOffer(id, offerId)`, then **Pay Sharma Traders** with `source = "credit"` (§9). The money goes to the
   supplier, not the merchant.

## 11. Soundbox mode (hold to talk)

Full-screen dark UI, one big mic button, last answer in large text.

### Recording: use WAV so the server needs no ffmpeg

Android's `MediaRecorder` produces AAC/3GP/AMR, which the server can only read if `ffmpeg` is installed. Recording 16 kHz mono
16-bit PCM and writing a WAV header avoids that dependency entirely:

```kotlin
@SuppressLint("MissingPermission")
class WavRecorder(private val outFile: File) {
    private val sampleRate = 16_000
    private var record: AudioRecord? = null
    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        val minBuf = AudioRecord.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, sampleRate,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, minBuf * 2)
        record = rec
        rec.startRecording()
        job = scope.launch(Dispatchers.IO) {
            val pcm = ByteArrayOutputStream()
            val buf = ByteArray(minBuf)
            val maxBytes = sampleRate * 2 * 25                       // cap at ~25 s: speech-to-text takes short clips
            while (isActive && pcm.size() < maxBytes) {
                val n = rec.read(buf, 0, buf.size)
                if (n > 0) pcm.write(buf, 0, n)
            }
            writeWav(pcm.toByteArray())
        }
    }

    suspend fun stop(): File {
        record?.stop(); record?.release(); record = null
        job?.cancelAndJoin()
        return outFile
    }

    private fun writeWav(pcm: ByteArray) {
        val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()); h.putInt(36 + pcm.size); h.put("WAVE".toByteArray())
        h.put("fmt ".toByteArray()); h.putInt(16); h.putShort(1); h.putShort(1)          // PCM, mono
        h.putInt(sampleRate); h.putInt(sampleRate * 2); h.putShort(2); h.putShort(16)
        h.put("data".toByteArray()); h.putInt(pcm.size)
        outFile.outputStream().use { it.write(h.array()); it.write(pcm) }
    }
}
```

### Ask, show, speak

```kotlin
val wav = recorder.stop()
val out = api.voice(
    merchantId.toString().toRequestBody("text/plain".toMediaType()),
    MultipartBody.Part.createFormData("file", "q.wav", wav.asRequestBody("audio/wav".toMediaType())),
)
showText(out.text)                                 // large text, always shown
out.audioUrl?.let { player.setMediaItem(MediaItem.fromUri(it)); player.prepare(); player.play() }
```

- Total round trip is about 2-3 s (speech-to-text, agent, text-to-speech). Show a "listening…" then "thinking…" state.
- `audioUrl == null` means speech synthesis failed: still show `text`.
- `transcript` is what the server heard (Devanagari for Hindi). Show it small so the user can see misheard words.
- Fallback if the microphone fails or the hall is too noisy: a text box that calls `chat(channel = "voice")` and plays nothing,
  or reuses `voice` with a recorded clip.

### Announcements like a real Soundbox

Poll for events while the screen is open:

```kotlin
var last = 0
lifecycleScope.launch {
    repeatOnLifecycle(Lifecycle.State.STARTED) {
        while (true) {
            api.events(merchantId, last).forEach { e ->
                last = maxOf(last, e.id)
                playChime(); tts.speak(e.text, TextToSpeech.QUEUE_ADD, null, "event-${e.id}")   // "Rs 2,500 prapt hue"
            }
            delay(2_500)
        }
    }
}
```

Use Android's built-in `TextToSpeech` (locale `hi-IN`) for these short lines; they are not synthesized by the server.
Trigger one on stage with `POST /demo/simulate-customer-payment {"merchant_id":1,"amount":2500}`.

## 12. App state and the merchant switcher

- Keep `merchantId` in a `DataStore`/ViewModel. Default to Ramesh (`1`). There is no login.
- Hide a merchant switcher in settings: `merchants()` returns Ramesh, Neha and Vikas. Switching only changes `merchantId` and
  which tabs show (`gstScheme == "regular"` shows IMS; Vikas uses the web dashboard, not this app).
- Format money with `NumberFormat.getCurrencyInstance(Locale("en", "IN"))` (`₹1,12,400`), and pick `messageHi` or `messageEn`
  from the merchant's `language`.

## 13. Testing

```kotlin
// MockWebServer returns captured JSON; check your models parse it
val server = MockWebServer().apply { enqueue(MockResponse().setBody(File("home.json").readText())) ; start() }
```

Capture real fixtures with `curl localhost:8000/merchants/1/home > home.json`. The backend's own contract is in
`shared/openapi.json`.

Demo checklist before you go on stage: backend reset (`make reset`), `PUBLIC_BASE_URL` reachable from the phone, microphone
and camera permissions already granted, one practice run of each flow (the server caches repeat requests, so a rehearsed
demo is fast).
