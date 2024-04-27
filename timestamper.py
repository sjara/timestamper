"""
Application to trigger camera frames and collect the timing of TTL sources during experiments.

This version relies on a LabJack U3 device.

TO DO:
- Add saving a temp file when stopping the system.

DEBUG:
trig = np.array(tsApp.timestamper.timestamps_trigger_rising)
d = np.diff(trig)
clf(); hist(d*1000)

"""

import datetime
import time
import u3
import sys
from qtpy import QtWidgets, QtCore, QtGui
import numpy as np

DEFAULT_TRIGGER_RATE = 20 # In Hz
SAMPLING_PERIOD = 0.001  # In seconds

TRIGGER_PIN = 0
DIGITAL_INPUT_PINS = [6]  # [6, 7]
DIGITAL_INPUT_NAMES = ['sound']  # ['camera', 'sound']

BUTTON_COLORS = {'start': 'limegreen', 'stop': 'red'}
MIN_WINDOW_WIDTH = 200

class DummyDevice:
    """
    Dummy class to emulate the behavior of the LabJack device.
    """
    def getCalibrationData(self):
        pass

    def getFeedback(self, *args):
        pass

    def setFIOState(self, *args):
        pass
    
    def getFIOState(self, *args):
        value = 1 if (np.random.rand(1)<0.001) else 0
        return value

    def close(self):
        pass

class TimeStamper:
    """
    Class to timestamp the camera frames and other TTL sources.
    """
    def __init__(self, triggerpin=TRIGGER_PIN, inputpins=DIGITAL_INPUT_PINS,
                 inputnames=DIGITAL_INPUT_NAMES, dummy=False):
        """
        Initialize the Timestamper object.
        
        Args:
            pins (list): List of pins of LabJack to monitor as digital inputs.
        """
        if not dummy:
            self.device = DummyDevice()
        else:
            self.device = u3.U3()
            
        self.device.getCalibrationData()
        
        # -- Set FIOs to digial and direction to input --
        self.trigger_pin = triggerpin
        self.device.getFeedback(u3.BitDirWrite(self.trigger_pin, 1))
        self.input_pins = inputpins
        for ind in self.input_pins:
            self.device.getFeedback(u3.BitDirWrite(ind, 0))
        # FIXME: setting self.state could be done in one line with getFeedback()
        self.state = []
        for ind, pin in enumerate(self.input_pins):
            self.state.append(self.device.getFIOState(pin))
        self.input_names = inputnames
       
        self.start_time = datetime.datetime.now()
        self.timestamps_trigger_rising = []
        self.timestamps_trigger_falling = []
        self.timestamps_rising = [list() for _ in self.input_pins]
        self.timestamps_falling = [list() for _ in self.input_pins]
        
    def name_inputs(self, names):
        """
        Assign names to the digital inputs.
        """
        self.inputNames = names

    def trigger(self, state):
        """
        Set state of trigger (True=on, False=off)
        """
        self.device.setFIOState(self.trigger_pin, state)
        timestamp = datetime.datetime.now()
        timestamp_sec = (timestamp-self.start_time).total_seconds()
        if state:
            self.timestamps_trigger_rising.append(timestamp_sec)
        else:
            self.timestamps_trigger_falling.append(timestamp_sec)
        
    def poll(self):
        """
        Poll the digital inputs and get a timestamp if there is a change.
        """
        previousState = list(self.state)  # Copy the current state
        for ind, pin in enumerate(self.input_pins):
            self.state[ind] = self.device.getFIOState(pin)
        if self.state != previousState:
            timestamp = datetime.datetime.now()
            timestamp_sec = (timestamp-self.start_time).total_seconds()
            change_status = True
            for ind, pin in enumerate(self.input_pins):
                if self.state[ind] != previousState[ind]:
                    if self.state[ind] == 1:
                        self.timestamps_rising[ind].append(timestamp_sec)
                    else:
                        self.timestamps_falling[ind].append(timestamp_sec)
                    print(f'[{ind}:{self.state[ind]}] {timestamp_sec}')
                    #print(self.timestamps_rising)
                    #print(self.timestamps_falling)
        else:
            change_status = False
        return change_status
    
    def close(self):
        """
        Close the LabJack device and release the resources.
        """
        self.device.close()

        
class TimeStamperApp(QtWidgets.QMainWindow):
    def __init__(self, dummy=False):
        super().__init__()

        self.dummy = dummy
        self.polling = False
        self.trigger_state = False
        if 1: #not dummy:
            self.timestamper = TimeStamper()
            self.n_inputs = len(self.timestamper.input_pins)
            self.start_time = self.timestamper.start_time
        else:
            self.start_time = datetime.datetime.now()
            self.n_inputs = 2
        self.inputs = range(self.n_inputs)

        self.counter_rising = []
        self.counter_falling = []
        
        # -- Create polling timer --
        self.timerPoll = QtCore.QTimer(self)
        self.timerPoll.timeout.connect(self.poll)
        self.timerPoll.setInterval(int(SAMPLING_PERIOD * 1000))  # Convert to milliseconds

        # -- Create trigger timer --
        self.timer_trigger = QtCore.QTimer(self)
        self.timer_trigger.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer_trigger.timeout.connect(self.trigger)
        self.set_trigger_timer_half_interval(DEFAULT_TRIGGER_RATE)
        
        self.init_gui()
        self.stop_polling()

    def init_gui(self):
        self.setWindowTitle('TimeStamper')
        self.settings = QtCore.QSettings('timestamper', 'jaralab')
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(300, 300, 300, 200)
            self.center_on_screen()
        
        # -- Create start/stop button --
        self.button_startstop = QtWidgets.QPushButton('', self)
        self.button_startstop.clicked.connect(self.start_stop_polling)
        self.button_startstop.setMinimumHeight(100)
        button_font = QtGui.QFont(self.button_startstop.font())
        button_font.setPointSize(button_font.pointSize()+10)
        self.button_startstop.setFont(button_font)
        self.setMinimumWidth(MIN_WINDOW_WIDTH)

        # -- Create a "Save" button --
        self.button_save = QtWidgets.QPushButton('Save', self)
        self.button_save.setMinimumHeight(50)
        self.button_save.clicked.connect(self.save_timestamps)

        # -- Create other gui elements --
        self.label_trigger_rate = QtWidgets.QLabel(f'<b>Trigger rate (Hz):</b>', self)
        self.trigger_rate = QtWidgets.QLineEdit(str(DEFAULT_TRIGGER_RATE), self)
        self.label_trigger_period = QtWidgets.QLabel(f'</b>Period (ms):</b>', self)
        self.trigger_rate.textChanged.connect(self.update_trigger_period)
        self.label_starttime = QtWidgets.QLabel(f'<b>Start time:</b> {self.start_time}', self)
        self.label_rising = QtWidgets.QLabel(f'Input rising counter:', self)
        self.label_falling = QtWidgets.QLabel(f'Input falling counter:', self)
        self.status_bar = self.statusBar()
        self.status_bar.showMessage('Status: Idle')

        # -- Create a horizontal layout for trigger rate --
        trigger_rate_layout = QtWidgets.QHBoxLayout()
        trigger_rate_layout.addWidget(self.label_trigger_rate)
        trigger_rate_layout.addWidget(self.trigger_rate)
        trigger_rate_layout.addWidget(self.label_trigger_period)
        
        # -- Add graphical widgets to main window --
        self.central_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.button_startstop)
        layout.addWidget(self.label_starttime)
        
        layout.addLayout(trigger_rate_layout)
        layout.addWidget(self.label_rising)
        layout.addWidget(self.label_falling)
        layout.addStretch()
        layout.addWidget(self.button_save)
        self.central_widget.setLayout(layout)
        self.setCentralWidget(self.central_widget)
        self.update_trigger_period()
        
    @QtCore.Slot()
    def update_trigger_period(self):
        trigger_period_ms = 1000.0 / float(self.trigger_rate.text())
        self.label_trigger_period.setText(f'<b>Period (ms):</b> {trigger_period_ms:0.1f}')
    
    def set_trigger_timer_half_interval(self, trigger_rate):
        timer_half_interval = 0.5/trigger_rate
        self.timer_trigger.setInterval(int(timer_half_interval * 1000))  # Convert to ms
    
    @QtCore.Slot()
    def trigger(self):
        self.trigger_state = not self.trigger_state
        self.timestamper.trigger(self.trigger_state)
    
    @QtCore.Slot()
    def poll(self):
        change_status = self.timestamper.poll()
        if change_status:
            self.counter_rising = [len(self.timestamper.timestamps_rising[ind]) for ind in self.inputs]
            self.counter_falling = [len(self.timestamper.timestamps_falling[ind]) for ind in self.inputs]
            self.label_rising.setText(f'Input rising counter: {self.counter_rising[0]}')
            self.label_falling.setText(f'Input falling counter: {self.counter_falling[0]}')
            
    def start_stop_polling(self):
        if not self.polling:
            self.start_polling()
        else:
            self.stop_polling()

    def start_polling(self):
        self.polling = True
        self.button_startstop.setText('Stop')
        stylestr = 'QWidget {{ background-color: {} }}'.format(BUTTON_COLORS['stop'])
        self.button_startstop.setStyleSheet(stylestr)
        #self.label_status.setText("Status: Polling...")
        #self.status_bar.showMessage(f'[Start time: {self.start_time}] Status: Polling')
        self.status_bar.showMessage(f'Status: Polling and sending trigger')
        self.timerPoll.start()
        self.set_trigger_timer_half_interval(float(self.trigger_rate.text()))
        self.timer_trigger.start()

    def stop_polling(self):
        self.polling = False
        self.button_startstop.setText('Start')
        stylestr = 'QWidget {{ background-color: {} }}'.format(BUTTON_COLORS['start'])
        self.button_startstop.setStyleSheet(stylestr)
        #self.label_status.setText("Status: Idle")
        #self.status_bar.showMessage(f'[Start time: {self.start_time}] Status: Idle')
        self.status_bar.showMessage(f'Status: Idle')
        self.timerPoll.stop()
        self.timer_trigger.stop()
        self.timestamper.trigger(False)
        
    def center_on_screen(self):
        qr = self.frameGeometry()
        cp = QtWidgets.QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def save_timestamps(self):
        data = {}
        for name in self.timestamper.input_names:
            input_ind = self.timestamper.input_names.index(name)
            data[f'ts_{name}_rising'] = np.array(self.timestamper.timestamps_rising[input_ind])
            data[f'ts_{name}_falling'] = np.array(self.timestamper.timestamps_falling[input_ind])
        data['ts_trigger_rising'] = np.array(self.timestamper.timestamps_trigger_rising)
        data['ts_trigger_falling'] = np.array(self.timestamper.timestamps_trigger_falling)
        data['start_time'] = self.start_time.isoformat()
    
        options = QtWidgets.QFileDialog.Options()
        options |= QtWidgets.QFileDialog.DontUseNativeDialog
        fileName, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Timestamps", "",
                                                            "NPZ Files (*.npz)", options=options)

        if fileName:
            np.savez(fileName, **data)
            self.status_bar.showMessage(f'Saved to {fileName}')

    def closeEvent(self, event):
        self.settings.setValue('geometry', self.saveGeometry())
        if 1: #not self.dummy:
            self.timestamper.device.close()
        event.accept()

'''        
if __name__ == '__main__':
    ts = TimeStamper()
    ts.name_inputs(['sound', 'camera'])
'''
        
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    tsApp = TimeStamperApp(dummy=1)
    tsApp.show()
    sys.exit(app.exec_())    

# ts = tsApp.timestamper

# d = np.load('ts001.npz')
# for key,item in d.items(): print(f'{key}: {item}')
