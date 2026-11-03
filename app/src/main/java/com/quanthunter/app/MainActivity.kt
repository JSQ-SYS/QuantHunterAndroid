package com.quanthunter.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private val Navy = Color(0xFF101B2B)
private val Panel = Color(0xFF1B2A40)
private val Accent = Color(0xFF65A9FF)
private val Green = Color(0xFF27C281)
private val Red = Color(0xFFFF6677)
private val Muted = Color(0xFF9EADC1)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { QuantApp() }
    }
}

data class StockSignal(
    val code: String, val name: String, val score: Double,
    val price: Double, val change: Double, val signal: String, val reason: String
)

@Composable
fun QuantApp() {
    var baseUrl by remember { mutableStateOf("http://10.0.2.2:8000") }
    var activeTab by remember { mutableStateOf("扫描") }
    var status by remember { mutableStateOf("未连接数据服务") }
    var busy by remember { mutableStateOf(false) }
    var resultText by remember { mutableStateOf("请先启动电脑端 Python 行情服务，再点击连接。") }
    var stocks by remember { mutableStateOf(listOf<StockSignal>()) }
    var scoreMin by remember { mutableStateOf("75") }
    var backtestText by remember { mutableStateOf("回测需要导入包含真实收盘竞价价和次日开盘竞价价的 CSV 数据。") }
    val scope = rememberCoroutineScope()

    MaterialTheme(colorScheme = darkColorScheme(
        primary = Accent, background = Navy, surface = Panel,
        onBackground = Color.White, onSurface = Color.White
    )) {
        Column(Modifier.fillMaxSize().background(Navy).padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()) {
                Column {
                    Text("尾盘猎手", fontSize = 25.sp, fontWeight = FontWeight.Bold, color = Color.White)
                    Text("QUANT  ·  沪深主板隔夜信号系统", color = Muted, fontSize = 11.sp)
                }
                Surface(color = Color(0xFF173B35), shape = RoundedCornerShape(20.dp)) {
                    Text("信号模式", color = Green, modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp), fontSize = 12.sp)
                }
            }
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatCard("数据源", "AkShare", "电脑端服务", Modifier.weight(1f))
                StatCard("最低评分", scoreMin, "满分 100", Modifier.weight(1f))
                StatCard("市场范围", "主板", "沪深 A 股", Modifier.weight(1f))
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("扫描", "卖出信号", "回测", "设置").forEach { tab ->
                    FilterChip(selected = activeTab == tab, onClick = { activeTab = tab },
                        label = { Text(tab, fontSize = 12.sp) })
                }
            }
            Spacer(Modifier.height(10.dp))
            when (activeTab) {
                "扫描" -> {
                    Text("行情服务地址", color = Muted, fontSize = 12.sp)
                    UrlField(baseUrl) { baseUrl = it }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            busy = true
                            scope.launch {
                                val r = apiGet(baseUrl, "/api/health")
                                status = r
                                resultText = r
                                busy = false
                            }
                        }, modifier = Modifier.weight(1f)) { Text("连接服务") }
                        Button(onClick = {
                            busy = true
                            scope.launch {
                                val r = apiGet(baseUrl, "/api/scan?min_score=${scoreMin.toDoubleOrNull() ?: 75.0}")
                                try {
                                    val j = JSONObject(r)
                                    val arr = j.optJSONArray("items") ?: JSONArray()
                                    stocks = (0 until arr.length()).map { i ->
                                        val x = arr.getJSONObject(i)
                                        StockSignal(x.optString("symbol"), x.optString("name"),
                                            x.optDouble("score"), x.optDouble("price"),
                                            x.optDouble("change_pct"), x.optString("signal"),
                                            x.optString("reason"))
                                    }
                                    status = "扫描完成：${stocks.size} 个候选"
                                    resultText = j.optString("message", status)
                                } catch (_: Exception) {
                                    status = "请求失败"
                                    resultText = r
                                }
                                busy = false
                            }
                        }, modifier = Modifier.weight(1f), enabled = !busy) { Text("开始扫描") }
                    }
                    Text(status, color = Accent, fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(stocks) { s -> StockCard(s) }
                    }
                    if (stocks.isEmpty()) Text(resultText, color = Muted, fontSize = 13.sp)
                }
                "卖出信号" -> {
                    Text("次日竞价卖出监控", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                    Text("卖出监控接口需要你把持仓和竞价观察数据提交到服务端。AkShare 不保证提供 9:20 虚拟撮合价。", color = Muted)
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = {
                        busy = true
                        scope.launch {
                            resultText = apiGet(baseUrl, "/api/positions")
                            busy = false
                        }
                    }, enabled = !busy) { Text("读取持仓监控") }
                    Text(resultText, color = Muted, fontSize = 12.sp)
                }
                "回测" -> {
                    Text("历史回测", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                    Text("上传真实竞价历史 CSV 后由 Python 服务端执行回测。日线收盘价不能替代收盘集合竞价成交价。", color = Muted)
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = {
                        busy = true
                        scope.launch {
                            backtestText = apiGet(baseUrl, "/api/backtest/status")
                            busy = false
                        }
                    }, enabled = !busy) { Text("检查回测服务") }
                    Text(backtestText, color = Muted, fontSize = 12.sp)
                }
                else -> {
                    Text("系统设置", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                    Text("API 地址", color = Muted)
                    UrlField(baseUrl) { baseUrl = it }
                    Text("最低评分（默认75）", color = Muted)
                    UrlField(scoreMin) { scoreMin = it.filter { c -> c.isDigit() || c == '.' } }
                    Text("默认模拟/信号模式；不自动下单。电脑端服务需与手机处于可访问网络。", color = Muted, fontSize = 12.sp)
                }
            }
            Spacer(Modifier.height(8.dp))
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text("风险提示：信号不等于成交。A股 T+1，跌停、停牌、排队及流动性风险可能导致无法按预期卖出。",
                color = Muted, fontSize = 10.sp)
        }
    }
}

@Composable
fun StatCard(title: String, value: String, sub: String, modifier: Modifier = Modifier) {
    Surface(modifier, color = Panel, shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.padding(10.dp)) {
            Text(title, color = Muted, fontSize = 10.sp)
            Text(value, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 17.sp)
            Text(sub, color = Muted, fontSize = 9.sp)
        }
    }
}

@Composable
fun UrlField(value: String, onValue: (String) -> Unit) {
    Surface(color = Panel, shape = RoundedCornerShape(10.dp), modifier = Modifier.fillMaxWidth()) {
        BasicTextField(value, onValue, modifier = Modifier.padding(12.dp).fillMaxWidth(),
            singleLine = true, textStyle = androidx.compose.ui.text.TextStyle(color = Color.White, fontSize = 13.sp))
    }
}

@Composable
fun StockCard(s: StockSignal) {
    Surface(color = Panel, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("${s.name}  ${s.code}", color = Color.White, fontWeight = FontWeight.Bold)
                    Text(s.signal, color = Accent, fontSize = 11.sp)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("评分 ${"%.1f".format(s.score)}", color = Color.White, fontWeight = FontWeight.Bold)
                    Text("${"%.2f".format(s.price)}  ${"%.2f".format(s.change)}%",
                        color = if (s.change >= 0) Red else Green, fontSize = 12.sp)
                }
            }
            Spacer(Modifier.height(5.dp))
            Text(s.reason, color = Muted, fontSize = 11.sp)
        }
    }
}

suspend fun apiGet(base: String, path: String): String = withContext(Dispatchers.IO) {
    try {
        val url = URL(base.trimEnd('/') + path)
        val c = (url.openConnection() as HttpURLConnection)
        c.connectTimeout = 8000
        c.readTimeout = 20000
        c.requestMethod = "GET"
        val stream = if (c.responseCode in 200..299) c.inputStream else c.errorStream
        val body = stream.bufferedReader().use { it.readText() }
        c.disconnect()
        body
    } catch (e: Exception) {
        """{"error":"${e.message ?: "连接失败"}","hint":"请确认电脑端 FastAPI 已启动，手机与电脑网络互通，API 地址填写正确。"}"""
    }
}
