package com.example.gsr_mobile

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.TextView

class GsrUpdateReceiver(
    private val gsrText: TextView,
    private val ecgText: TextView,
    private val statusText: TextView,
    private val polarStatusText: TextView
) : BroadcastReceiver() {

    companion object {
        val intentFilter = android.content.IntentFilter("GSR_UPDATE")
    }

    override fun onReceive(context: Context?, intent: Intent?) {
        intent ?: return
        val gsr = intent.getIntExtra("gsr", -1)
        val ecg = intent.getIntExtra("ecg", -1)
        val hc06 = intent.getBooleanExtra("hc06", false)
        val polar = intent.getBooleanExtra("polar", false)

        if (gsr != -1) gsrText.text = "GSR: $gsr"
        if (ecg != -1) ecgText.text = "ECG: $ecg"
        statusText.text = "GSR: ${if (hc06) "подключено" else "не подключено"}"
        polarStatusText.text = "Polar: ${if (polar) "подключено" else "не подключено"}"
    }
}