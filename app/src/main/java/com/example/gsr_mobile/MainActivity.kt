package com.example.gsr_mobile

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.Switch
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : Activity() {

    private lateinit var gsrText: TextView
    private lateinit var ecgText: TextView
    private lateinit var statusText: TextView
    private lateinit var polarStatusText: TextView
    private lateinit var receiver: GsrUpdateReceiver

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // UI элементы
        val btSwitch = findViewById<Switch>(R.id.btSwitch)
        gsrText = findViewById(R.id.gsrText)
        ecgText = findViewById(R.id.ecgText)
        statusText = findViewById(R.id.statusText)
        polarStatusText = findViewById(R.id.polarStatus)
        val recordButton = findViewById<Button>(R.id.recordButton)

        // Запрос разрешений
        requestPermissions()

        // Регистрируем BroadcastReceiver
        receiver = GsrUpdateReceiver(gsrText, ecgText, statusText, polarStatusText)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(receiver, GsrUpdateReceiver.intentFilter, RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(receiver, GsrUpdateReceiver.intentFilter)
        }

        // Переключатель сервиса
        btSwitch.setOnCheckedChangeListener { _, isChecked ->
            val intent = Intent(this, GsrService::class.java)
            if (isChecked) startService(intent) else stopService(intent)
        }

        // Кнопка записи
        recordButton.setOnClickListener {
            startService(Intent(this, GsrService::class.java).apply {
                putExtra("recording", true)
            })
        }
    }

    private fun requestPermissions() {
        val perms = mutableListOf<String>()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            perms.add(Manifest.permission.BLUETOOTH_CONNECT)
            perms.add(Manifest.permission.BLUETOOTH_SCAN)
        }

        perms.add(Manifest.permission.ACCESS_FINE_LOCATION)
        perms.add(Manifest.permission.ACCESS_COARSE_LOCATION)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            perms.add(Manifest.permission.FOREGROUND_SERVICE)
        }

        val missingPerms = perms.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missingPerms.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, missingPerms.toTypedArray(), 1)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(receiver)
    }
}
