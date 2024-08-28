# esp01s-bme280
Code and setup for humidity measurement with ESP-01s and BME280


## Connection
|3.3V Power supply|ESP-01s|BME280|
|:---------------:|:-----:|:----:|
|       Vo+       |  3V3  |  VCC |
|       Vo-       |  GND  |  GND |
|                 |  IO0  |  SCL |
|                 |  IO2  |  SDA |


## Programs
```mermaid
graph LR;
    Viewer["Viewer Python Program"];
    SensorA["Sensor A"];
    SensorB["Sensor B"];
    SensorN["Sensor ..."];
    UDP("UDP broadcast\n Port 12345");
    Viewer-->UDP-->SensorA;
    UDP-->SensorB;
    UDP-->SensorN;

    LabView["LabView VI"];
    Web("HTTP\n Port 12346")
    LabView --> Web --> Viewer

    Viewer --> log["Write to log files \n at /log"]
```
