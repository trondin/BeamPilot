import serial
import threading
import time
from queue import Queue

CMD_BUFF_DEPTH = 10
USB_PORT = '/dev/ttyUSB0'
BAUDRATE = 115200
WORK_SPEED = 2500
IDLE_SPEED = 2500

class GrblWindowTester:
    def __init__(self, port=USB_PORT, baudrate=BAUDRATE):
        self.ser = serial.Serial(port, baudrate, timeout=0, write_timeout=0)
        self.rx_buffer = bytearray()
        
        # Система окна команд
        self.window_size = CMD_BUFF_DEPTH  # Максимум команд в буфере
        self.pending_commands = 0  # Ожидающие ответа команды
        self.total_sent = 0
        self.total_ok = 0
        
        self.command_queue = Queue()  # Очередь для команд
        self.send_allowed = False  # Флаг для разрешения отправки команд
        
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
            # Если отправка разрешена, есть место в окне, очередь не пуста и передатчик готов
            if (self.send_allowed and
                self.pending_commands < self.window_size and 
                not self.command_queue.empty() and 
                self.ser.out_waiting == 0):
                
                # Отправляем команду
                cmd = self.command_queue.get()
                self.ser.write(cmd)
                
                # Обновляем счетчики
                self.pending_commands += 1
                self.total_sent += 1
            
            time.sleep(0.00001)  # 10 мкс
    
    def start(self):
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        time.sleep(0.1)
        
        self.rx_thread = threading.Thread(target=self.rx_interrupt_handler)
        self.tx_thread = threading.Thread(target=self.tx_interrupt_handler)
        
        self.rx_thread.daemon = True
        self.tx_thread.daemon = True
        
        self.rx_thread.start()
        self.tx_thread.start()
        
        print(f"Тест с окном команд (размер: {self.window_size}) запущен...")
        print("Цикл: 500 команд G1 X0.1 F1000, затем G0 X-50 F1500 в относительном режиме, пауза 5 сек, повтор.")
        
        while self.running:
            # Переключаем в относительный режим
            self.command_queue.put(b'$120=600\n')
            self.command_queue.put(b'$120=600\n')

            self.command_queue.put(b'G91\n')
            self.command_queue.put(f'F{WORK_SPEED}\n'.encode())
            self.command_queue.put(b'G1 X3.0\n')
            # Добавляем 500 команд G1 X0.1
            for _ in range(500):
                self.command_queue.put(b'G1 X0.1 S0000\n')
            # Добавляем команду возврата G0 X-50
            self.command_queue.put(f'G1 X-53 F{IDLE_SPEED}\n'.encode())
            #self.command_queue.put(f'G0 X-50 F{IDLE_SPEED}\n'.encode())            
            
            # Разрешаем отправку команд после их накопления
            print(f"Накоплено {self.command_queue.qsize()} команд, начинаем отправку...")
            self.send_allowed = True
            
            # Ждем завершения всех команд (очередь пуста и нет ожидающих ok)
            while self.running and (not self.command_queue.empty() or self.pending_commands > 0):
                time.sleep(0.1)
            
            if not self.running:
                break
            
            # Запрещаем отправку перед следующим циклом накопления
            self.send_allowed = False
            print("Все команды отправлены, пауза 5 секунд перед следующим циклом...")
            
            # Пауза 5 секунд перед следующим циклом
            time.sleep(2)

    def stop(self):
        print("\nИнициировано завершение работы...")
        self.running = False
        self.send_allowed = False
        
        # Очищаем очередь команд
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
            except:
                pass
        
        # Ждем завершения всех отправленных команд
        while self.pending_commands > 0:
            print(f"Ожидание завершения: {self.pending_commands} команд в обработке")
            time.sleep(0.1)
        
        # Закрываем последовательный порт
        if self.ser.is_open:
            try:
                self.ser.flush()
                self.ser.close()
                print("Последовательный порт закрыт")
            except Exception as e:
                print(f"Ошибка при закрытии порта: {e}")
        
        # Ждем завершения потоков
        if self.rx_thread:
            self.rx_thread.join(timeout=1.0)
        if self.tx_thread:
            self.tx_thread.join(timeout=1.0)       
        print("Программа завершена")

if __name__ == "__main__":
    tester = GrblWindowTester('/dev/ttyUSB0', 115200)
    try:
        tester.start()
    except KeyboardInterrupt:
        print("\nОжидание завершения текущего движения...")
        while tester.pending_commands > 0 or not tester.command_queue.empty():
            time.sleep(0.1)
        tester.stop()