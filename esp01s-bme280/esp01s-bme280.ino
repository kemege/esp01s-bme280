#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <SPI.h>
#include <Adafruit_BME280.h>
#include <WiFiUdp.h>

// Configuration constants
const char* WIFI_SSID = "117";
const char* WIFI_PASSWORD = "117117117";
const char* WIFI_HOSTNAME = "test_name.local";
const char* DEVICE_NAME = "test_name";
const int SERVER_PORT = 80;
const int UDP_PORT = 12345;

// Global variables for reading sensors
float temperature, humidity, pressure, altitude;

// Initialize web server
ESP8266WebServer server(SERVER_PORT);

// Initialize sensor on I2C
Adafruit_BME280 bme;
bool sensorUp = false;

// initialize UDP
WiFiUDP Udp;
char packetBuffer[UDP_TX_PACKET_MAX_SIZE + 1];  //buffer to hold incoming packet,
String ReplyBuffer = "";                        // a string to send back
String command = "";

void setup() {
  // Initialize Serial
  Serial.begin(115200);
  delay(1000);
  Serial.println("");

  Serial.println("===== Environment sensor with BME280 =====");
  Serial.printf("Name: %s\n", DEVICE_NAME);

  // Initialize sensor
  Wire.begin(2, 0);
  if (bme.begin(0x76, &Wire)) {
    sensorUp = true;
    Serial.println("Found BME280 sensor.");
  } else {
    Serial.println("ERROR: Cannot find a valid BME280 sensor.");
  }
  Serial.print("SensorID was: 0x");
  Serial.println(bme.sensorID(), 16);

  // Connect to WiFi
  WiFi.hostname(WIFI_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Try connecting to WiFi
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");

  Serial.printf("Connected to WiFi at %s\n", WIFI_SSID);
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // request at root for information
  server.on("/", []() {
    server.send(200, "text/plain", "ESP8266 with BME280 at " + String(DEVICE_NAME));
    delay(100);
  });

  // request at /data for readings
  server.on("/data", []() {
    read_data();
    server.send(200, "application/json", "{\"device\":\"" + String(DEVICE_NAME) + "\",\"temperature\":" + String(temperature) + ",\"humidity\":" + String(humidity) + "}");
  });

  server.begin();
  Serial.println("HTTP server is up.");

  // Initialize UDP server
  while (!Udp.begin(UDP_PORT)) {
    Serial.print("+");
    yield();
  }
  Serial.println("UDP server is up.");
}

void loop() {
  // Handle HTTP requests
  server.handleClient();

  handleUdpDiscovery();
}

void read_data() {
  if (sensorUp) {
    temperature = bme.readTemperature();
    humidity = bme.readHumidity();
    pressure = bme.readPressure();
    altitude = bme.readAltitude(1013.25);  // 1013.25 for sea level pressure
  } else {
    Serial.println("ERROR: sensor is not up, returning dummy data.");
    temperature = 0.0;
    humidity = 0.0;
    pressure = 0.0;
    altitude = 0.0;
  }
}

void handleUdpDiscovery() {
  int packetSize = Udp.parsePacket();
  if (packetSize) {
    Serial.printf("Received packet of size %d from %s:%d\n    (to %s:%d, free heap = %d B)\n",
                  packetSize,
                  Udp.remoteIP().toString().c_str(), Udp.remotePort(),
                  Udp.destinationIP().toString().c_str(), Udp.localPort(),
                  ESP.getFreeHeap());

    // read the packet into packetBufffer
    int n = Udp.read(packetBuffer, UDP_TX_PACKET_MAX_SIZE);
    packetBuffer[n] = 0; // Ensure zero at end-of-string
    command = String(packetBuffer);

    if (command.equalsIgnoreCase("RST")) {
      ESP.restart();
    } else if (command.equalsIgnoreCase("get ip")) {
      Udp.beginPacket(Udp.remoteIP(), Udp.remotePort());
      ReplyBuffer = "{\"ip\":\"" + WiFi.localIP().toString() + "\",\"mac\":\"" + WiFi.macAddress() + "\"}";
      Udp.write(ReplyBuffer.c_str());
      Udp.endPacket();
    } else if (command.equalsIgnoreCase("get data")) {
      read_data();
      Udp.beginPacket(Udp.remoteIP(), Udp.remotePort());
      ReplyBuffer = "{\"device\":\"" + String(DEVICE_NAME) + 
        "\",\"temperature\":" + String(temperature) + 
        ",\"humidity\":" + String(humidity) + 
        ",\"pressure\":" + String(pressure) + 
        ",\"altitude\":" + String(altitude) + "}";
      Udp.write(ReplyBuffer.c_str());
      Udp.endPacket();
    } else {
      Serial.println("Unrecognized contents:");
      Serial.println(packetBuffer);
    }
  }
}
