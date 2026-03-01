package com.example.gsr_mobile

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothSocket
import android.bluetooth.BluetoothStatusCodes
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.MediaStore
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.OutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class GsrService : Service() {

    private val deviceAddress = "98:DA:60:0F:64:87" // HC-06
    private val polarAddress = "FA:D3:AC:2D:99:81"  // Polar

    private val uuid = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    private val pmdServiceUuid: UUID = UUID.fromString("FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8")
    private val pmdControlUuid: UUID = UUID.fromString("FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8")
    private val pmdDataUuid: UUID = UUID.fromString("FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8")
    private val cccdUuid: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    private val ecgStartCommand = byteArrayOf(
        0x02, 0x00, 0x00, 0x01, 0x82.toByte(),
        0x00, 0x01, 0x01, 0x0E, 0x00
    )


    private var polarControlCharacteristic: BluetoothGattCharacteristic? = null
    private var polarDataCharacteristic: BluetoothGattCharacteristic? = null

    private var socket: BluetoothSocket? = null
    private var bluetoothGatt: BluetoothGatt? = null
    private var csvStream: OutputStream? = null
    private var recording = false

    private var hc06Connected = false
    private var polarConnected = false
    private var polarDataReceived = false
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onBind(intent: Intent?): IBinder? = null

    private fun bluetoothAdapterOrNull(): BluetoothAdapter? {
        val manager = getSystemService(BluetoothManager::class.java) ?: return null
        return manager.adapter
    }

    override fun onCreate() {
        super.onCreate()
        startForegroundNotification()
        Thread { connectHC06() }.start()
        Thread { connectPolar() }.start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        recording = intent?.getBooleanExtra("recording", false) ?: false
        if (recording && csvStream == null) setupCsv()
        if (!recording) closeCsv()
        return START_STICKY
    }

    private fun startForegroundNotification() {
        val channelId = "gsr_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(channelId, "GSR Service", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("GSR Service")
            .setContentText("Подключение к HC-06 и Polar")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .build()
        startForeground(1, notification)
    }

    private fun sendUpdate(gsr: Int? = null, ecg: Int? = null) {
        val intent = Intent(GsrUpdateReceiver.ACTION_GSR_UPDATE).apply {
            `package` = packageName
            putExtra("hc06", hc06Connected)
            putExtra("polar", polarConnected)
            gsr?.let { putExtra("gsr", it) }
            ecg?.let { putExtra("ecg", it) }
        }
        sendBroadcast(intent)

        if (recording) {
            val line = "${System.currentTimeMillis()},${gsr ?: ""},${ecg ?: ""}\n"
            try {
                csvStream?.write(line.toByteArray())
                csvStream?.flush()
            } catch (_: Exception) {
                // ignore stream write errors while service keeps running
            }
        }
    }

    private fun connectHC06() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
            ) return
            val adapter = bluetoothAdapterOrNull() ?: return
            adapter.cancelDiscovery()

            val device = adapter.getRemoteDevice(deviceAddress)
            socket = device.createRfcommSocketToServiceRecord(uuid)
            socket?.connect()

            hc06Connected = true
            sendUpdate()

            val input = socket?.inputStream ?: return
            val buffer = ByteArray(1024)
            var lineBuffer = ""

            while (true) {
                val count = input.read(buffer)
                if (count <= 0) break
                lineBuffer += String(buffer, 0, count)
                var idx = lineBuffer.indexOf('\n')
                while (idx >= 0) {
                    val line = lineBuffer.substring(0, idx).trim()
                    lineBuffer = lineBuffer.substring(idx + 1)
                    idx = lineBuffer.indexOf('\n')
                    parseHC06Line(line)
                }
            }
        } catch (se: SecurityException) {
            Log.e("GSR", "HC06 permission error", se)
        } catch (e: Exception) {
            Log.e("GSR", "HC06 error", e)
        } finally {
            hc06Connected = false
            sendUpdate()
            try {
                socket?.close()
            } catch (_: Exception) {
                // ignore close errors
            }
            socket = null
        }
    }

    private fun parseHC06Line(line: String) {
        val gsr = line.split(",")
            .firstOrNull { it.startsWith("GSR:") }
            ?.substringAfter("GSR:")
            ?.toIntOrNull()

        if (gsr != null) sendUpdate(gsr = gsr)
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                polarConnected = true
                polarDataReceived = false
                sendUpdate()
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
            ) return
                try {
                    gatt.discoverServices()
                } catch (se: SecurityException) {
                    Log.e("GSR", "Polar discoverServices permission error", se)
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                polarConnected = false
                polarDataReceived = false
                polarControlCharacteristic = null
                polarDataCharacteristic = null
                mainHandler.removeCallbacksAndMessages(null)
                sendUpdate()
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
            ) return
            try {
                val service = gatt.getService(pmdServiceUuid) ?: run {
                    Log.e("GSR", "Polar PMD service not found")
                    return
                }
                val control = service.getCharacteristic(pmdControlUuid) ?: run {
                    Log.e("GSR", "Polar PMD control characteristic not found")
                    return
                }
                val data = service.getCharacteristic(pmdDataUuid) ?: run {
                    Log.e("GSR", "Polar PMD data characteristic not found")
                    return
                }

                polarControlCharacteristic = control
                polarDataCharacteristic = data

                gatt.setCharacteristicNotification(control, true)
                val controlDescriptor = control.getDescriptor(cccdUuid) ?: run {
                    Log.e("GSR", "Polar control CCCD descriptor not found")
                    return
                }

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    val result = gatt.writeDescriptor(controlDescriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                    if (result != BluetoothStatusCodes.SUCCESS) {
                        Log.e("GSR", "Failed to write Polar control CCCD, status=$result")
                    }
                } else {
                    @Suppress("DEPRECATION")
                    run {
                        controlDescriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                        val ok = gatt.writeDescriptor(controlDescriptor)
                        if (!ok) {
                            Log.e("GSR", "Failed to write Polar control CCCD (legacy)")
                        }
                    }
                }
            } catch (se: SecurityException) {
                Log.e("GSR", "Polar service discovery permission error", se)
            }
        }

        override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            super.onDescriptorWrite(gatt, descriptor, status)
            if (descriptor.uuid != cccdUuid) return

            if (descriptor.characteristic.uuid == pmdControlUuid) {
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    Log.e("GSR", "Polar control CCCD write failed with status=$status")
                    return
                }

                val data = polarDataCharacteristic ?: run {
                    Log.e("GSR", "Polar data characteristic is null while enabling notifications")
                    return
                }
                gatt.setCharacteristicNotification(data, true)
                val dataDescriptor = data.getDescriptor(cccdUuid) ?: run {
                    Log.e("GSR", "Polar data CCCD descriptor not found")
                    return
                }

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    val result = gatt.writeDescriptor(dataDescriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                    if (result != BluetoothStatusCodes.SUCCESS) {
                        Log.e("GSR", "Failed to write Polar data CCCD, status=$result")
                    }
                } else {
                    @Suppress("DEPRECATION")
                    run {
                        dataDescriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                        val ok = gatt.writeDescriptor(dataDescriptor)
                        if (!ok) {
                            Log.e("GSR", "Failed to write Polar data CCCD (legacy)")
                        }
                    }
                }
                return
            }

            if (descriptor.characteristic.uuid == pmdDataUuid) {
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    Log.i("GSR", "Polar data notifications enabled, starting ECG stream")
                    startPolarEcgStream(gatt, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
                } else {
                    Log.e("GSR", "Polar data CCCD write failed with status=$status")
                }
            }
        }

        override fun onCharacteristicWrite(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            super.onCharacteristicWrite(gatt, characteristic, status)
            if (characteristic.uuid == pmdControlUuid) {
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    Log.i("GSR", "Polar ECG start command acknowledged")
                    schedulePolarRetry(gatt)
                } else {
                    Log.e("GSR", "Polar ECG start command failed, status=$status")
                }
            }
        }

        @Deprecated("Deprecated in Android API 33")
        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            onPolarCharacteristicChanged(characteristic.uuid, characteristic.value)
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            onPolarCharacteristicChanged(characteristic.uuid, value)
        }
    }

    private fun onPolarCharacteristicChanged(uuid: UUID, value: ByteArray) {
        if (uuid == pmdControlUuid) {
            Log.i("GSR", "Polar control notification: ${value.joinToString(separator = " ") { b -> "%02X".format(b) }}")
            return
        }
        if (uuid != pmdDataUuid) return

        polarDataReceived = true
        Log.d("GSR", "Polar data packet size=${value.size}, frameType=${if (value.isNotEmpty()) value[0].toInt() and 0xFF else -1}")
        parsePolarData(value)
    }

    private fun startPolarEcgStream(gatt: BluetoothGatt, writeType: Int) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
        ) return

        val control = polarControlCharacteristic ?: run {
            Log.e("GSR", "Cannot start Polar ECG: control characteristic is null")
            return
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val result = gatt.writeCharacteristic(
                    control,
                    ecgStartCommand,
                    writeType
                )
                if (result != BluetoothStatusCodes.SUCCESS) {
                    Log.e("GSR", "Failed to send Polar ECG start command, status=$result")
                }
            } else {
                @Suppress("DEPRECATION")
                run {
                    control.value = ecgStartCommand
                    control.writeType = writeType
                    val ok = gatt.writeCharacteristic(control)
                    if (!ok) {
                        Log.e("GSR", "Failed to send Polar ECG start command (legacy)")
                    }
                }
            }
        } catch (se: SecurityException) {
            Log.e("GSR", "Polar ECG start permission error", se)
        }
    }


    private fun schedulePolarRetry(gatt: BluetoothGatt) {
        mainHandler.postDelayed({
            if (!polarDataReceived && polarConnected) {
                Log.w("GSR", "No Polar data after start command, retrying with WRITE_TYPE_NO_RESPONSE")
                startPolarEcgStream(gatt, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
            }
        }, 2000)
    }

    private fun connectPolar() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
        ) return
        try {
            val adapter = bluetoothAdapterOrNull() ?: return
            val device: BluetoothDevice = adapter.getRemoteDevice(polarAddress)
            bluetoothGatt = device.connectGatt(this, false, gattCallback)
        } catch (se: SecurityException) {
            Log.e("GSR", "Polar permission error", se)
            polarConnected = false
            sendUpdate()
        } catch (e: Exception) {
            Log.e("GSR", "Polar error", e)
            polarConnected = false
            sendUpdate()
        }
    }

    private fun parsePolarData(data: ByteArray) {
        if (data.isEmpty()) return
        if (data[0].toInt() != 0x00) return
        if (data.size <= 10) return
        var offset = 10
        val step = 3

        while (offset + 2 < data.size) {
            val raw = (data[offset].toInt() and 0xFF) or
                ((data[offset + 1].toInt() and 0xFF) shl 8) or
                ((data[offset + 2].toInt() and 0xFF) shl 16)
            val ecg = if (raw and 0x800000 != 0) raw or -0x1000000 else raw
            sendUpdate(ecg = ecg)
            offset += step
        }
    }

    @SuppressLint("InlinedApi")
    private fun setupCsv() {
        val sdf = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault())
        val name = "GSR_${sdf.format(Date())}.csv"
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "text/csv")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            }
        }

        val collection: Uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStore.Downloads.EXTERNAL_CONTENT_URI
        } else {
            MediaStore.Files.getContentUri("external")
        }

        val uri = contentResolver.insert(collection, values)
        csvStream = uri?.let { contentResolver.openOutputStream(it) }
        csvStream?.write("timestamp,gsr,ecg\n".toByteArray())
    }

    private fun closeCsv() {
        try {
            csvStream?.close()
        } catch (_: Exception) {
            // ignore close errors
        }
        csvStream = null
    }

    override fun onDestroy() {
        super.onDestroy()
        mainHandler.removeCallbacksAndMessages(null)
        try {
            socket?.close()
        } catch (_: Exception) {
            // ignore close errors
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED) {
                    bluetoothGatt?.close()
                }
            } else {
                bluetoothGatt?.close()
            }
        } catch (se: SecurityException) {
            Log.e("GSR", "Error while closing GATT due to permission", se)
        }
    }
}
