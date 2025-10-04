import serial
import threading
import time

CMD_BUFF_DEPTH = 10
USB_PORT = '/dev/ttyUSB0'
BAUDRATE = 115200

class GrblWindowTester:
    def __init__(self, port=USB_PORT, baudrate=BAUDRATE):
        self.ser = serial.Serial(port, baudrate, timeout=0, write_timeout=0)
        self.rx_buffer = bytearray()
        
        # Система окна команд
        self.window_size = CMD_BUFF_DEPTH  # Максимум команд в буфере
        self.pending_commands = 0  # Ожидающие ответа команды
        self.total_sent = 0
        self.total_ok = 0
        
        self.commands = [b'M5\n', b'G0 X0\n', b'G0 Y0\n', b'G0 Z0\n']
        self.current_command = 0
        self.running = True
        
    def rx_interrupt_handler(self):
        """Прерывание по приему - обработка ok"""
        while self.running:
            if self.ser.in_waiting > 0:
                data = self.ser.read(self.ser.in_waiting)
                self.rx_buffer.extend(data)
                
                # Ищем все ok в буфере
                while b'ok\r' in self.rx_buffer:
                    ok_pos = self.rx_buffer.find(b'ok\r')
                    # Удаляем ok\r из буфера
                    self.rx_buffer = self.rx_buffer[ok_pos + 3:]
                    
                    # Уменьшаем счетчик ожидающих команд
                    if self.pending_commands > 0:
                        self.pending_commands -= 1
                        self.total_ok += 1
            
            time.sleep(0.00001)  # 10 мкс
    
    def tx_interrupt_handler(self):
        """Прерывание по передаче - отправка с учетом окна"""
        while self.running:
            # Если есть место в окне и передатчик готов
            if (self.pending_commands < self.window_size and 
                self.ser.out_waiting == 0):
                
                # Отправляем команду
                cmd = self.commands[self.current_command]
                self.ser.write(cmd)
                
                # Обновляем счетчики
                self.pending_commands += 1
                self.total_sent += 1
                self.current_command = (self.current_command + 1) % len(self.commands)
            
            time.sleep(0.00001)  # 10 мкс
    
    def start(self):
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.1)
        
        rx_thread = threading.Thread(target=self.rx_interrupt_handler)
        tx_thread = threading.Thread(target=self.tx_interrupt_handler)
        
        rx_thread.daemon = True
        tx_thread.daemon = True
        
        rx_thread.start()
        tx_thread.start()
        
        print(f"Тест с окном команд (размер: {self.window_size}) запущен...")
        print("Команды: M5, G0 X0, G0 Y0, G0 Z0")
        
        # Статистика
        
        #last_time = time.time()
        #last_sent = 0
        #last_ok = 0
        
        while self.running:
            pass
            time.sleep(0.5)  # Статистика каждые 0.5 сек
            
            #now = time.time()            
            #last_time = now

        

if __name__ == "__main__":
    tester = GrblWindowTester('/dev/ttyUSB0', 115200)
    try:
        tester.start()
    except KeyboardInterrupt:
        tester.running = False
        print("\nОстановка теста")