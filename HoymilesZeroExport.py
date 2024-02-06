# HoymilesZeroExport - https://github.com/reserve85/HoymilesZeroExport
# Copyright (C) 2023, Tobias Kraft

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = "Tobias Kraft"
__version__ = "1.69"

import requests
import time
from requests.auth import HTTPBasicAuth
from requests.auth import HTTPDigestAuth
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from configparser import ConfigParser
from pathlib import Path
import sys
from packaging import version
import argparse 

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', help='Override configuration file path')
args = parser.parse_args()

try:
    config = ConfigParser()
    
    baseconfig = str(Path.joinpath(Path(__file__).parent.resolve(), "HoymilesZeroExport_Config.ini"))
    if args.config:
        config.read([baseconfig, args.config])
    else:
        config.read(baseconfig)

    ENABLE_LOG_TO_FILE = config.getboolean('COMMON', 'ENABLE_LOG_TO_FILE')
    LOG_BACKUP_COUNT = config.getint('COMMON', 'LOG_BACKUP_COUNT')
except Exception as e:
    logger.info('Error on reading ENABLE_LOG_TO_FILE, set it to DISABLED')
    ENABLE_LOG_TO_FILE = False
    if hasattr(e, 'message'):
        logger.error(e.message)
    else:
        logger.error(e)

if ENABLE_LOG_TO_FILE:
    if not os.path.exists(Path.joinpath(Path(__file__).parent.resolve(), 'log')):
        os.makedirs(Path.joinpath(Path(__file__).parent.resolve(), 'log'))

    rotating_file_handler = TimedRotatingFileHandler(
        filename=Path.joinpath(Path.joinpath(Path(__file__).parent.resolve(), 'log'),'log'),
        when='midnight',
        interval=2,
        backupCount=LOG_BACKUP_COUNT)

    formatter = logging.Formatter(
        '%(asctime)s %(levelname)-8s %(message)s')
    rotating_file_handler.setFormatter(formatter)
    logger.addHandler(rotating_file_handler)

logger.info('Log write to file: %s', ENABLE_LOG_TO_FILE)
logger.info('Python Version: ' + sys.version)
try:
    assert sys.version_info >= (3,6)
except:
    logger.info('Error: your Python version is too old, this script requires version 3.6 or newer. Please update your Python.')
    sys.exit()

def CastToInt(pValueToCast):
    try:
        result = int(pValueToCast)
        return result
    except:
        result = 0
    try:
        result = int(float(pValueToCast))
        return result
    except:
        logger.error("Exception at CastToInt")
        raise

def WaitForAck(pInverterId, pTimeoutInS):
    try:
        timeout = pTimeoutInS
        timeout_start = time.time()
        while time.time() < timeout_start + timeout:
            time.sleep(0.5)
            ack = DTU.GetLimitAck(pInverterId)
            if ack:
                break
        if ack:
            logger.info('%s: Inverter "%s": Limit acknowledged', DTU.TypeName(), NAME[pInverterId])
        else:
            logger.info('%s: Inverter "%s": Limit timeout!', DTU.TypeName(), NAME[pInverterId])
        return ack
    except:
        logger.error("Exception at WaitForAck")
        return False

def SetLimitInverterLimit(pInverterId, pLimit):
    logger.info('%s: Inverter "%s": setting new limit from %s Watt to %s Watt', DTU.TypeName(), NAME[pInverterId], CastToInt(CURRENT_LIMIT[pInverterId]), CastToInt(pLimit))
    DTU.SendLimit(pInverterId, pLimit)
    CURRENT_LIMIT[pInverterId] = pLimit

def SetLimitWithPriority(pLimit):
    try:
        if not hasattr(SetLimitWithPriority, "LastLimit"):
            SetLimitWithPriority.LastLimit = CastToInt(0)
        if not hasattr(SetLimitWithPriority, "LastLimitAck"):
            SetLimitWithPriority.LastLimitAck = bool(False)

        if (SetLimitWithPriority.LastLimit == CastToInt(pLimit)) and SetLimitWithPriority.LastLimitAck:
            logger.info("Inverterlimit was already accepted at %s Watt",CastToInt(pLimit))
            return
        if (SetLimitWithPriority.LastLimit == CastToInt(pLimit)) and not SetLimitWithPriority.LastLimitAck:
            logger.info("Inverterlimit %s Watt was previously not accepted by the inverter, trying again...",CastToInt(pLimit))

        logger.info("setting new limit to %s Watt",CastToInt(pLimit))
        SetLimitWithPriority.LastLimit = CastToInt(pLimit)
        SetLimitWithPriority.LastLimitAck = True
        if (CastToInt(pLimit) <= GetMinWattFromAllInverters()):
            pLimit = 0 # set only minWatt for every inv.
        RemainingLimit = CastToInt(pLimit)
        for j in range (1,6):
            if GetMaxWattFromAllInvertersSamePrio(j) <= 0:
                continue
            if RemainingLimit >= GetMaxWattFromAllInvertersSamePrio(j):
                LimitPrio = GetMaxWattFromAllInvertersSamePrio(j)
            else:
                LimitPrio = RemainingLimit    
            RemainingLimit = RemainingLimit - LimitPrio

            for i in range(INVERTER_COUNT):
                if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
                    continue
                if HOY_BATTERY_PRIORITY[i] != j:
                    continue
                Factor = HOY_MAX_WATT[i] / GetMaxWattFromAllInvertersSamePrio(j)         
                NewLimit = CastToInt(LimitPrio*Factor)
                NewLimit = ApplyLimitsToSetpointInverter(i, NewLimit)
                if HOY_COMPENSATE_WATT_FACTOR[i] != 1:
                    logger.info('%s: Inverter "%s": compensate Limit from %s Watt to %s Watt', DTU.TypeName(), NAME[i], CastToInt(NewLimit), CastToInt(NewLimit * HOY_COMPENSATE_WATT_FACTOR[i]))
                    NewLimit = CastToInt(NewLimit * HOY_COMPENSATE_WATT_FACTOR[i])
                    NewLimit = ApplyLimitsToMaxInverterLimits(i, NewLimit)

                if (NewLimit == CastToInt(CURRENT_LIMIT[i])) and LASTLIMITACKNOWLEDGED[i]:
                    continue   

                LASTLIMITACKNOWLEDGED[i] = True

                SetLimitInverterLimit(i, NewLimit)
                if not WaitForAck(i, SET_LIMIT_TIMEOUT_SECONDS):
                    SetLimitWithPriority.LastLimitAck = False
                    LASTLIMITACKNOWLEDGED[i] = False
    except:
        logger.error("Exception at SetLimitWithPriority")
        SetLimitWithPriority.LastLimitAck = False
        raise

def SetLimit(pLimit):
    try:
        if not GetMixedMode() and GetBatteryMode() and GetPriorityMode():
            SetLimitWithPriority(CastToInt(pLimit))
            return

        if not hasattr(SetLimit, "LastLimit"):
            SetLimit.LastLimit = CastToInt(0)
        if not hasattr(SetLimit, "LastLimitAck"):
            SetLimit.LastLimitAck = bool(False)

        if (SetLimit.LastLimit == CastToInt(pLimit)) and SetLimit.LastLimitAck:
            logger.info("Inverterlimit was already accepted at %s Watt",CastToInt(pLimit))
            return
        if (SetLimit.LastLimit == CastToInt(pLimit)) and not SetLimit.LastLimitAck:
            logger.info("Inverterlimit %s Watt was previously not accepted by at least one inverter, trying again...",CastToInt(pLimit))

        logger.info("setting new limit to %s Watt",CastToInt(pLimit))
        SetLimit.LastLimit = CastToInt(pLimit)
        SetLimit.LastLimitAck = True
        if (CastToInt(pLimit) <= GetMinWattFromAllInverters()):
            pLimit = 0 # set only minWatt for every inv.
        for i in range(INVERTER_COUNT):
            if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
                continue
            Factor = HOY_MAX_WATT[i] / GetMaxWattFromAllInverters()
            NewLimit = CastToInt(pLimit*Factor)
            NewLimit = ApplyLimitsToSetpointInverter(i, NewLimit)
            if HOY_COMPENSATE_WATT_FACTOR[i] != 1:
                logger.info('%s: Inverter "%s": compensate Limit from %s Watt to %s Watt', DTU.TypeName(), NAME[i], CastToInt(NewLimit), CastToInt(NewLimit * HOY_COMPENSATE_WATT_FACTOR[i]))
                NewLimit = CastToInt(NewLimit * HOY_COMPENSATE_WATT_FACTOR[i])
                NewLimit = ApplyLimitsToMaxInverterLimits(i, NewLimit)

            if (NewLimit == CastToInt(CURRENT_LIMIT[i])) and LASTLIMITACKNOWLEDGED[i]:
                continue

            LASTLIMITACKNOWLEDGED[i] = True

            SetLimitInverterLimit(i, NewLimit)
            if not WaitForAck(i, SET_LIMIT_TIMEOUT_SECONDS):
                SetLimit.LastLimitAck = False
                LASTLIMITACKNOWLEDGED[i] = False
    except:
        logger.error("Exception at SetLimit")
        SetLimit.LastLimitAck = False
        raise

def GetHoymilesAvailable():
    try:
        GetHoymilesAvailable = False
        for i in range(INVERTER_COUNT):
            try:
                WasAvail = AVAILABLE[i]
                AVAILABLE[i] = DTU.FetchInverterAvailable(i)
                logger.info('%s: Inverter "%s" reachable: %s', DTU.TypeName(), NAME[i], AVAILABLE[i])
                if AVAILABLE[i]:
                    GetHoymilesAvailable = True
                    if not WasAvail:
                        if hasattr(SetLimit, "LastLimit"):
                            SetLimit.LastLimit = CastToInt(0)
                        if hasattr(SetLimit, "LastLimitAck"):
                            SetLimit.LastLimitAck = bool(False)
                        if hasattr(SetLimitWithPriority, "LastLimit"):
                            SetLimitWithPriority.LastLimit = CastToInt(0)
                        if hasattr(SetLimitWithPriority, "LastLimitAck"):
                            SetLimitWithPriority.LastLimitAck = bool(False)
                        LASTLIMITACKNOWLEDGED[i] = False
                        GetHoymilesInfo()
            except Exception as e:
                AVAILABLE[i] = False
                logger.error("Exception at GetHoymilesAvailable, Inverter %s (%s) not reachable", i, NAME[i])
                if hasattr(e, 'message'):
                    logger.error(e.message)
                else:
                    logger.error(e)
        return GetHoymilesAvailable
    except:
        logger.error('Exception at GetHoymilesAvailable')
        raise

def FetchInfo(pInverterId):
    name, serial, temperature = DTU.FetchInfo(pInverterId)
    SERIAL_NUMBER[pInverterId] = serial
    TEMPERATURE[pInverterId] = temperature
    NAME[pInverterId] = name
    logger.info('%s: Inverter "%s" / serial number "%s" / temperature %s', DTU.TypeName(), NAME[pInverterId], SERIAL_NUMBER[pInverterId], TEMPERATURE[pInverterId])


def GetHoymilesInfo():
    try:
        for i in range(INVERTER_COUNT):
            try:
                if not AVAILABLE[i]:
                    continue
                FetchInfo(i)
            except Exception as e:
                logger.error('Exception at GetHoymilesInfo, Inverter "%s" not reachable', NAME[i])
                if hasattr(e, 'message'):
                    logger.error(e.message)
                else:
                    logger.error(e)
    except:
        logger.error("Exception at GetHoymilesInfo")
        raise

def GetHoymilesPanelMinVoltageFromDTU(pInverterId):
    PanelVDC = DTU.GetHoymilesPanelMinVoltage(pInverterId)
    minVdc = float('inf')
    for i in range(len(PanelVDC)):
        if (minVdc > PanelVDC[i]) and (PanelVDC[i] > 5):
            minVdc = PanelVDC[i]
    if minVdc == float('inf'):
        minVdc = 0

    # save last 5 min-values in list and return the "highest" value.
    HOY_PANEL_VOLTAGE_LIST[pInverterId].append(minVdc)
    if len(HOY_PANEL_VOLTAGE_LIST[pInverterId]) > 5:
        HOY_PANEL_VOLTAGE_LIST[pInverterId].pop(0)
    max_value = None
    for num in HOY_PANEL_VOLTAGE_LIST[pInverterId]:
        if (max_value is None or num > max_value):
            max_value = num

    logger.info('Lowest panel voltage inverter "%s": %s Volt',NAME[pInverterId],max_value)
    return max_value

def GetHoymilesPanelMinVoltage(pInverterId):
    if not hasattr(GetHoymilesPanelMinVoltage, "HoymilesPanelMinVoltageArray"):
        GetHoymilesPanelMinVoltage.HoymilesPanelMinVoltageArray = [] 
    try:
        if not AVAILABLE[pInverterId]:
            return 0
        HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST[pInverterId].append(GetHoymilesPanelMinVoltageFromDTU(pInverterId))

        # calculate mean over last x values
        if len(HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST[pInverterId]) > 5:
            HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST[pInverterId].pop(0)
        from statistics import mean
        
        logger.info('Average min-panel voltage, inverter "%s": %s Volt',NAME[pInverterId], mean(HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST[pInverterId]))
        return mean(HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST[pInverterId])
    except:
        logger.error("Exception at GetHoymilesPanelMinVoltage, Inverter %s not reachable", pInverterId)
        raise

def SetHoymilesPowerStatus(pInverterId, pActive):
    try:
        if not AVAILABLE[pInverterId]:
            return
        if SET_POWERSTATUS_CNT > 0:
            if not hasattr(SetHoymilesPowerStatus, "LastPowerStatus"):
                SetHoymilesPowerStatus.LastPowerStatus = []
                SetHoymilesPowerStatus.LastPowerStatus = [False for i in range(INVERTER_COUNT)]
            if not hasattr(SetHoymilesPowerStatus, "SamePowerStatusCnt"):
                SetHoymilesPowerStatus.SamePowerStatusCnt = []
                SetHoymilesPowerStatus.SamePowerStatusCnt = [0 for i in range(INVERTER_COUNT)]
            if SetHoymilesPowerStatus.LastPowerStatus[pInverterId] == pActive:
                SetHoymilesPowerStatus.SamePowerStatusCnt[pInverterId] = SetHoymilesPowerStatus.SamePowerStatusCnt[pInverterId] + 1
            else:
                SetHoymilesPowerStatus.LastPowerStatus[pInverterId] = pActive
                SetHoymilesPowerStatus.SamePowerStatusCnt[pInverterId] = 0
            if SetHoymilesPowerStatus.SamePowerStatusCnt[pInverterId] > SET_POWERSTATUS_CNT:
                if pActive:
                    logger.info("Retry Counter exceeded: Inverter PowerStatus already ON")
                else:
                    logger.info("Retry Counter exceeded: Inverter PowerStatus already OFF")
                return
        DTU.SetPowerStatus(pInverterId, pActive)
        time.sleep(SET_POWER_STATUS_DELAY_IN_SECONDS)
    except:
        logger.error("Exception at SetHoymilesPowerStatus")
        raise
    
def GetNumberArray(pExcludedPanels):
    lclExcludedPanelsList = pExcludedPanels.split(',')
    result = []
    for number_str in lclExcludedPanelsList:
        if number_str == '':
            continue
        number = int(number_str.strip())
        result.append(number)
    return result

def GetCheckBattery():
    try:
        result = False
        for i in range(INVERTER_COUNT):
            try:
                if not AVAILABLE[i]:
                    continue
                if not HOY_BATTERY_MODE[i]:
                    result = True
                    continue
                minVoltage = GetHoymilesPanelMinVoltage(i)

                if minVoltage <= HOY_BATTERY_THRESHOLD_OFF_LIMIT_IN_V[i]:
                    SetHoymilesPowerStatus(i, False)
                    HOY_BATTERY_GOOD_VOLTAGE[i] = False
                    HOY_MAX_WATT[i] = HOY_BATTERY_REDUCE_WATT[i]

                elif minVoltage <= HOY_BATTERY_THRESHOLD_REDUCE_LIMIT_IN_V[i]:
                    if HOY_MAX_WATT[i] != HOY_BATTERY_REDUCE_WATT[i]:
                        HOY_MAX_WATT[i] = HOY_BATTERY_REDUCE_WATT[i]
                        SetLimit.LastLimit = -1

                elif minVoltage >= HOY_BATTERY_THRESHOLD_ON_LIMIT_IN_V[i]:
                    SetHoymilesPowerStatus(i, True)
                    if not HOY_BATTERY_GOOD_VOLTAGE[i]:
                        SetLimitInverterLimit(i, HOY_MAX_WATT[i])
                        WaitForAck(i, SET_LIMIT_TIMEOUT_SECONDS)
                        SetLimit.LastLimit = -1
                    HOY_BATTERY_GOOD_VOLTAGE[i] = True
                    HOY_MAX_WATT[i] = HOY_BATTERY_NORMAL_WATT[i]

                elif minVoltage >= HOY_BATTERY_THRESHOLD_NORMAL_LIMIT_IN_V[i]:
                    if HOY_MAX_WATT[i] != HOY_BATTERY_NORMAL_WATT[i]:
                        HOY_MAX_WATT[i] = HOY_BATTERY_NORMAL_WATT[i]
                        SetLimit.LastLimit = -1

                if HOY_BATTERY_GOOD_VOLTAGE[i]:
                    result = True
            except:
                logger.error("Exception at CheckBattery, Inverter %s not reachable", i)
        return result
    except:
        logger.error("Exception at CheckBattery")
        raise

def GetHoymilesTemperature():
    try:
        for i in range(INVERTER_COUNT):
            try:
                if not AVAILABLE[i]:
                    continue
                TEMPERATURE[i] = str(DTU.FetchTemperature(i)) + ' degC'
                logger.info('%s: Inverter "%s" temperature: %s', DTU.TypeName(), NAME[i], TEMPERATURE[i])
            except:
                logger.error("Exception at GetHoymilesTemperature, Inverter %s not reachable", i)
    except:
        logger.error("Exception at GetHoymilesTemperature")
        raise

def GetHoymilesActualPower():
    try:
        Watts = INTERMEDIATE_POWERMETER.GetPowermeterWatts()
        logger.info(f"intermediate meter {INTERMEDIATE_POWERMETER.__class__.__name__}: {Watts} Watt")
        return Watts
    except:
        logger.error("Exception at GetHoymilesActualPower")
        raise

def GetPowermeterWatts():
    try:
        Watts = POWERMETER.GetPowermeterWatts()
        logger.info(f"powermeter {POWERMETER.__class__.__name__}: {Watts} Watt")
        return Watts
    except:
        logger.error("Exception at GetPowermeterWatts")
        raise

def CutLimitToProduction(pSetpoint):
    if pSetpoint != GetMaxWattFromAllInverters():
        ActualPower = GetHoymilesActualPower()
        # prevent the setpoint from running away...
        if pSetpoint > ActualPower + (GetMaxWattFromAllInverters() * MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER / 100):
            pSetpoint = CastToInt(ActualPower + (GetMaxWattFromAllInverters() * MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER / 100))
            logger.info('Cut limit to %s Watt, limit was higher than %s percent of live-production', CastToInt(pSetpoint), MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER)
    return CastToInt(pSetpoint)

def ApplyLimitsToSetpoint(pSetpoint):
    if pSetpoint > GetMaxWattFromAllInverters():
        pSetpoint = GetMaxWattFromAllInverters()
    if pSetpoint < GetMinWattFromAllInverters():
        pSetpoint = GetMinWattFromAllInverters()
    return pSetpoint

def ApplyLimitsToSetpointInverter(pInverter, pSetpoint):
    if pSetpoint > HOY_MAX_WATT[pInverter]:
        pSetpoint = HOY_MAX_WATT[pInverter]
    if pSetpoint < HOY_MIN_WATT[pInverter]:
        pSetpoint = HOY_MIN_WATT[pInverter]
    return pSetpoint

def ApplyLimitsToMaxInverterLimits(pInverter, pSetpoint):
    if pSetpoint > HOY_INVERTER_WATT[pInverter]:
        pSetpoint = HOY_INVERTER_WATT[pInverter]
    if pSetpoint < HOY_MIN_WATT[pInverter]:
        pSetpoint = HOY_MIN_WATT[pInverter]
    return pSetpoint

# Max possible Watts, can be reduced on battery mode
def GetMaxWattFromAllInverters():
    maxWatt = 0
    for i in range(INVERTER_COUNT):
        if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
            continue
        maxWatt = maxWatt + HOY_MAX_WATT[i]
    return maxWatt

# Max possible Watts, can be reduced on battery mode
def GetMaxWattFromAllInvertersSamePrio(pPriority):
    maxWatt = 0
    for i in range(INVERTER_COUNT):
        if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
            continue
        if HOY_BATTERY_PRIORITY[i] == pPriority:
            maxWatt = maxWatt + HOY_MAX_WATT[i]
    return maxWatt

# Max possible Watts (physically) - Inverter Specification!
def GetMaxInverterWattFromAllInverters():
    maxWatt = 0
    for i in range(INVERTER_COUNT):
        if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
            continue
        maxWatt = maxWatt + HOY_INVERTER_WATT[i]
    return maxWatt

def GetMinWattFromAllInverters():
    minWatt = 0
    for i in range(INVERTER_COUNT):
        if (not AVAILABLE[i]) or (not HOY_BATTERY_GOOD_VOLTAGE[i]):
            continue
        minWatt = minWatt + HOY_MIN_WATT[i]
    return minWatt

def GetMixedMode():
    #if battery mode and custom priority use SetLimitWithPriority
    for i in range(INVERTER_COUNT):
        for j in range(INVERTER_COUNT):
            if (HOY_BATTERY_MODE[i] != HOY_BATTERY_MODE[j]):
                return True
    return False

def GetBatteryMode():
    for i in range(INVERTER_COUNT):
        if HOY_BATTERY_MODE[i]:
            return True
    return False

def GetPriorityMode():
    for i in range(INVERTER_COUNT):
        for j in range(INVERTER_COUNT):
            if HOY_BATTERY_PRIORITY[i] != HOY_BATTERY_PRIORITY[j]:
                return True
    return False

class Powermeter:
    def GetPowermeterWatts(self) -> int:
        raise NotImplementedError()

class Tasmota(Powermeter):
    def __init__(self, ip: str, json_status: str, json_payload_mqtt_prefix: str, json_power_mqtt_label: str, json_power_input_mqtt_label: str, json_power_output_mqtt_label: str, json_power_calculate: bool):
        self.ip = ip
        self.json_status = json_status
        self.json_payload_mqtt_prefix = json_payload_mqtt_prefix
        self.json_power_mqtt_label = json_power_mqtt_label
        self.json_power_input_mqtt_label = json_power_input_mqtt_label
        self.json_power_output_mqtt_label = json_power_output_mqtt_label
        self.json_power_calculate = json_power_calculate

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        return requests.get(url, timeout=10).json()

    def GetPowermeterWatts(self):
        ParsedData = self.GetJson('/cm?cmnd=status%2010')
        if not self.json_power_calculate:
            return CastToInt(ParsedData[self.json_status][self.json_payload_mqtt_prefix][self.json_power_mqtt_label])
        else:
            input = ParsedData[self.json_status][self.json_payload_mqtt_prefix][self.json_power_input_mqtt_label]
            ouput = ParsedData[self.json_status][self.json_payload_mqtt_prefix][self.json_power_output_mqtt_label]
            return CastToInt(input - ouput)

class Shelly(Powermeter):
    def __init__(self, ip: str, user: str, password: str):
        self.ip = ip
        self.user = user
        self.password = password

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        headers = {"content-type": "application/json"}
        return requests.get(url, headers=headers, auth=(self.user, self.password), timeout=10).json()

    def GetRpcJson(self, path):
        url = f'http://{self.ip}/rpc{path}'
        headers = {"content-type": "application/json"}
        return requests.get(url, headers=headers, auth=HTTPDigestAuth(self.user, self.password), timeout=10).json()

    def GetPowermeterWatts(self) -> int:
        raise NotImplementedError()

class Shelly1PM(Shelly):
    def GetPowermeterWatts(self):
        return CastToInt(self.GetJson('/status')['meters'][0]['power'])

class ShellyPlus1PM(Shelly):
    def GetPowermeterWatts(self):
        return CastToInt(self.GetRpcJson('/Switch.GetStatus?id=0')['apower'])

class ShellyEM(Shelly):
    def GetPowermeterWatts(self):
        return sum(CastToInt(emeter['power']) for emeter in self.GetJson('/status')['emeters'])

class Shelly3EM(Shelly):
    def GetPowermeterWatts(self):
        return CastToInt(self.GetJson('/status')['total_power'])

class Shelly3EMPro(Shelly):
    def GetPowermeterWatts(self):
        return CastToInt(self.GetRpcJson('/EM.GetStatus?id=0')['total_act_power'])

class Shrdzm(Powermeter):
    def __init__(self, ip: str, user: str, password: str):
        self.ip = ip
        self.user = user
        self.password = password

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        return requests.get(url, timeout=10).json()

    def GetPowermeterWatts(self):
        ParsedData = self.GetJson(f'/getLastData?user={self.user}&password={self.password}')
        return CastToInt(CastToInt(ParsedData['1.7.0']) - CastToInt(ParsedData['2.7.0']))

class Emlog(Powermeter):
    def __init__(self, ip: str, meterindex: str):
        self.ip = ip
        self.meterindex = meterindex

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        return requests.get(url, timeout=10).json()

    def GetPowermeterWatts(self):
        ParsedData = self.GetJson(f'/pages/getinformation.php?heute&meterindex={self.meterindex}')
        return CastToInt(ParsedData['Leistung170'])

class IoBroker(Powermeter):
    def __init__(self, ip: str, port: str, current_power_alias: str, power_calculate: bool, power_input_alias: str, power_output_alias: str):
        self.ip = ip
        self.port = port
        self.current_power_alias = current_power_alias
        self.power_calculate = power_calculate
        self.power_input_alias = power_input_alias
        self.power_output_alias = power_output_alias

    def GetJson(self, path):
        url = f'http://{self.ip}:{self.port}{path}'
        return requests.get(url, timeout=10).json()

    def GetPowermeterWatts(self):
        if not self.power_calculate:
            ParsedData = self.GetJson(f'/getBulk/{self.current_power_alias}')
            for item in ParsedData:
                if item['id'] == self.current_power_alias:
                    return CastToInt(item['val'])
        else:
            ParsedData = self.GetJson(f'/getBulk/{self.power_input_alias},{self.power_output_alias}')
            for item in ParsedData:
                if item['id'] == self.power_input_alias:
                    input = CastToInt(item['val'])
                if item['id'] == self.power_output_alias:
                    output = CastToInt(item['val'])
            return CastToInt(input - output)

class HomeAssistant(Powermeter):
    def __init__(self, ip: str, port: str, access_token: str, current_power_entity: str, power_calculate: bool, power_input_alias: str, power_output_alias: str):
        self.ip = ip
        self.port = port
        self.access_token = access_token
        self.current_power_entity = current_power_entity
        self.power_calculate = power_calculate
        self.power_input_alias = power_input_alias
        self.power_output_alias = power_output_alias

    def GetJson(self, path):
        url = f"http://{self.ip}:{self.port}{path}"
        headers = {"Authorization": "Bearer " + self.access_token, "content-type": "application/json"}
        return requests.get(url, headers=headers, timeout=10).json()

    def GetPowermeterWatts(self):
        if not self.power_calculate:
            ParsedData = self.GetJson(f"/api/states/{self.current_power_entity}")
            return CastToInt(ParsedData['state'])
        else:
            ParsedData = self.GetJson(f"/api/states/{self.power_input_alias}")
            input = CastToInt(ParsedData['state'])
            ParsedData = self.GetJson(f"/api/states/{self.power_output_alias}")
            output = CastToInt(ParsedData['state'])
            return CastToInt(input - output)

class VZLogger(Powermeter):
    def __init__(self, ip: str, port: str, uuid: str):
        self.ip = ip
        self.port = port
        self.uuid = uuid

    def GetJson(self):
        url = f"http://{self.ip}:{self.port}/{self.uuid}"
        return requests.get(url, timeout=10).json()

    def GetPowermeterWatts(self):
        return CastToInt(self.GetJson()['data'][0]['tuples'][0][1])

class DTU(Powermeter):
    def __init__(self, inverter_count: int):
        self.inverter_count = inverter_count

    def TypeName(self):
        raise NotImplementedError()

    def GetACPower(self, pInverterId: int):
        raise NotImplementedError()

    def GetPowermeterWatts(self):
        return sum(self.GetACPower(pInverterId) for pInverterId in range(self.inverter_count) if AVAILABLE[pInverterId] and HOY_BATTERY_GOOD_VOLTAGE[pInverterId])

    def CheckVersion(self):
        pass

    def SendLimit(self, pInverterId: int, pLimit: int):
        raise NotImplementedError()

    def FetchInfo(self, pInverterId: int):
        raise NotImplementedError()

    def GetLimitAck(self, pInverterId: int):
        raise NotImplementedError()

    def GetHoymilesPanelMinVoltage(self, pInverterId: int):
        raise NotImplementedError()

    def SetPowerStatus(self, pInverterId: int, pActive: bool):
        raise NotImplementedError()

    def FetchInverterAvailable(self, pInverterId: int):
        raise NotImplementedError()

    def FetchTemperature(self, pInverterId: int):
        raise NotImplementedError()


class AhoyDTU(DTU):
    def __init__(self, inverter_count: int, ip: str):
        super().__init__(inverter_count)
        self.ip = ip
        self.version = None

    def TypeName(self):
        return 'Ahoy'

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        return requests.get(url, timeout=10).json()

    def GetACPower(self, pInverterId):
        ParsedData = self.GetJson('/api/live')
        ActualPower_index = ParsedData["ch0_fld_names"].index("P_AC")
        ParsedData = self.GetJson(f'/api/inverter/id/{pInverterId}')
        return CastToInt(ParsedData["ch"][0][ActualPower_index])

    def CheckVersion(self):
        MinVersion = '0.7.29'
        if self.GetVersion() < version.parse(MinVersion):
            logger.error(
                'Error: Your AHOY Version is too old! Please update at least to Version %s - you can find the newest dev-releases here: https://github.com/lumapu/ahoy/actions',
                MinVersion)
            quit()

    def FetchInfo(self, pInverterId: int):
        ParsedData = self.GetJson('/api/live')
        temp_index = ParsedData["ch0_fld_names"].index("Temp")
        ParsedData = self.GetJson(f'/api/inverter/id/{pInverterId}')
        return [ParsedData['name'], ParsedData['serial'], ParsedData["ch"][0][temp_index]]

    def GetLimitAck(self, pInverterId: int):
        ParsedData = self.GetJson(f'/api/inverter/id/{pInverterId}')
        return bool(ParsedData["power_limit_ack"])

    def FetchInverterAvailable(self, pInverterId: int):
        ParsedData = self.GetJson('/api/index')
        return bool(ParsedData["inverter"][pInverterId]["is_avail"])

    def GetHoymilesPanelMinVoltage(self, pInverterId: int):
        ParsedData = self.GetJson('/api/live')
        PanelVDC_index = ParsedData["fld_names"].index("U_DC")
        ParsedData = self.GetJson(f'/api/inverter/id/{pInverterId}')
        PanelVDC = []
        ExcludedPanels = GetNumberArray(HOY_BATTERY_IGNORE_PANELS[pInverterId])
        for i in range(1, len(ParsedData['ch']), 1):
            if i not in ExcludedPanels:
                PanelVDC.append(float(ParsedData['ch'][i][PanelVDC_index]))
        return PanelVDC

    def GetVersion(self):
        if self.version is None:
            system_data = self.GetJson('/api/system')
            self.version = version.parse(str((system_data["version"])))
            logger.info('%s: Current Version: %s', self.TypeName(), self.version)
        return self.version

    def GetLimitFactor(self):
        if self.GetVersion() < version.parse('0.8.39'):
            return 1
        else:
            return 10

    def SendLimit(self, pInverterId: int, pLimit: int):
        url = f"http://{self.ip}/api/ctrl"
        limit_factor = self.GetLimitFactor()
        data = f'''{{"id": {pInverterId}, "cmd": "limit_nonpersistent_absolute", "val": {pLimit * limit_factor}}}'''
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        requests.post(url, data=data, headers=headers)

    def SetPowerStatus(self, pInverterId: int, pActive: bool):
        url = f"http://{self.ip}/api/ctrl"
        data = f'''{{"id": {pInverterId}, "cmd": "power", "val": {CastToInt(pActive == True)}}}'''
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        if pActive:
            logger.info('%s: Inverter "%s": Turn on', self.TypeName(), NAME[pInverterId])
        else:
            logger.info('%s: Inverter "%s": Turn off', self.TypeName(), NAME[pInverterId])
        requests.post(url, data=data, headers=headers)

    def FetchTemperature(self, pInverterId: int):
        ParsedData = self.GetJson('/api/live')
        temp_index = ParsedData["ch0_fld_names"].index("Temp")
        ParsedData = self.GetJson(f'/api/inverter/id/{pInverterId}')
        return ParsedData["ch"][0][temp_index]

class OpenDTU(DTU):
    def __init__(self, inverter_count: int, ip: str, user: str, password: str):
        super().__init__(inverter_count)
        self.ip = ip
        self.user = user
        self.password = password

    def TypeName(self):
        return 'OpenDTU'

    def GetJson(self, path):
        url = f'http://{self.ip}{path}'
        return requests.get(url, auth=HTTPBasicAuth(self.user, self.password), timeout=10).json()

    def GetACPower(self, pInverterId):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        return CastToInt(ParsedData['inverters'][pInverterId]['AC']['0']['Power']['v'])

    def GetHoymilesPanelMinVoltage(self, pInverterId: int):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        PanelVDC = []
        ExcludedPanels = GetNumberArray(HOY_BATTERY_IGNORE_PANELS[pInverterId])
        for i in range(len(ParsedData['inverters'][pInverterId]['DC'])):
            if i not in ExcludedPanels:
                PanelVDC.append(float(ParsedData['inverters'][pInverterId]['DC'][str(i)]['Voltage']['v']))
        return PanelVDC

    def FetchInfo(self, pInverterId: int):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        return [
            ParsedData['inverters'][pInverterId]['name'],
            ParsedData['inverters'][pInverterId]['serial'],
            round(float(ParsedData['inverters'][pInverterId]['INV']['0']['Temperature']['v'])),
        ]

    def GetLimitAck(self, pInverterId: int):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        return bool(ParsedData['inverters'][pInverterId]['limit_ack'])

    def GetInverterAvailable(self, pInverterId: int):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        return bool(ParsedData["inverters"][pInverterId]["is_avail"])


    def SendLimit(self, pInverterId: int, pLimit: int):
        relLimit = CastToInt(pLimit / HOY_INVERTER_WATT[pInverterId] * 100)
        url = f"http://{self.ip}/api/limit/config"
        data = f'''data={{"serial":"{SERIAL_NUMBER[pInverterId]}", "limit_type":1, "limit_value":{relLimit}}}'''
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        requests.post(url, data=data, auth=HTTPBasicAuth(self.user, self.password), headers=headers)

    def SetPowerStatus(self, pInverterId: int, pActive: bool):
        url = f"http://{self.ip}/api/power/config"
        data = f'''data={{"serial":"{SERIAL_NUMBER[pInverterId]}", "power":{CastToInt(pActive == True)}}}'''
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if pActive:
            logger.info('%s: Inverter "%s": Turn on', self.TypeName(), NAME[pInverterId])
        else:
            logger.info('%s: Inverter "%s": Turn off', self.TypeName(), NAME[pInverterId])
        requests.post(url, data=data, auth=HTTPBasicAuth(self.user, self.password), headers=headers)

    def FetchTemperature(self, pInverterId: int):
        ParsedData = self.GetJson('/api/livedata/status/inverters')
        return round(float((ParsedData['inverters'][pInverterId]['INV']['0']['Temperature']['v'])), 1)

def CreatePowermeter() -> Powermeter:
    shelly_ip = config.get('SHELLY', 'SHELLY_IP')
    shelly_user = config.get('SHELLY', 'SHELLY_USER')
    shelly_pass = config.get('SHELLY', 'SHELLY_PASS')
    if config.getboolean('SELECT_POWERMETER', 'USE_SHELLY_EM'):
        return ShellyEM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_POWERMETER', 'USE_SHELLY_3EM'):
        return Shelly3EM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_POWERMETER', 'USE_SHELLY_3EM_PRO'):
        return Shelly3EMPro(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_POWERMETER', 'USE_TASMOTA'):
        return Tasmota(
            config.get('TASMOTA', 'TASMOTA_IP'),
            config.get('TASMOTA', 'TASMOTA_JSON_STATUS'),
            config.get('TASMOTA', 'TASMOTA_JSON_PAYLOAD_MQTT_PREFIX'),
            config.get('TASMOTA', 'TASMOTA_JSON_POWER_MQTT_LABEL'),
            config.get('TASMOTA', 'TASMOTA_JSON_POWER_INPUT_MQTT_LABEL'),
            config.get('TASMOTA', 'TASMOTA_JSON_POWER_OUTPUT_MQTT_LABEL'),
            config.getboolean('TASMOTA', 'TASMOTA_JSON_POWER_CALCULATE', fallback=False)
        )
    elif config.getboolean('SELECT_POWERMETER', 'USE_SHRDZM'):
        return Shrdzm(
            config.get('SHRDZM', 'SHRDZM_IP'),
            config.get('SHRDZM', 'SHRDZM_USER'),
            config.get('SHRDZM', 'SHRDZM_PASS')
        )
    elif config.getboolean('SELECT_POWERMETER', 'USE_EMLOG'):
        return Emlog(
            config.get('EMLOG', 'EMLOG_IP'),
            config.get('EMLOG', 'EMLOG_METERINDEX')
        )
    elif config.getboolean('SELECT_POWERMETER', 'USE_IOBROKER'):
        return IoBroker(
            config.get('IOBROKER', 'IOBROKER_IP'),
            config.get('IOBROKER', 'IOBROKER_PORT'),
            config.get('IOBROKER', 'IOBROKER_CURRENT_POWER_ALIAS'),
            config.getboolean('IOBROKER', 'IOBROKER_POWER_CALCULATE'),
            config.get('IOBROKER', 'IOBROKER_POWER_INPUT_ALIAS'),
            config.get('IOBROKER', 'IOBROKER_POWER_OUTPUT_ALIAS')
        )
    elif config.getboolean('SELECT_POWERMETER', 'USE_HOMEASSISTANT'):
        return HomeAssistant(
            config.get('HOMEASSISTANT', 'HA_IP'),
            config.get('HOMEASSISTANT', 'HA_PORT'),
            config.get('HOMEASSISTANT', 'HA_ACCESSTOKEN'),
            config.get('HOMEASSISTANT', 'HA_CURRENT_POWER_ENTITY'),
            config.getboolean('HOMEASSISTANT', 'HA_POWER_CALCULATE'),
            config.get('HOMEASSISTANT', 'HA_POWER_INPUT_ALIAS'),
            config.get('HOMEASSISTANT', 'HA_POWER_OUTPUT_ALIAS')
        )
    elif config.getboolean('SELECT_POWERMETER', 'USE_VZLOGGER'):
        return VZLogger(
            config.get('VZLOGGER', 'VZL_IP'),
            config.get('VZLOGGER', 'VZL_PORT'),
            config.get('VZLOGGER', 'VZL_UUID')
        )
    else:
        raise Exception("Error: no powermeter defined!")

def CreateIntermediatePowermeter(dtu: DTU) -> Powermeter:
    shelly_ip = config.get('INTERMEDIATE_SHELLY', 'SHELLY_IP_INTERMEDIATE')
    shelly_user = config.get('INTERMEDIATE_SHELLY', 'SHELLY_USER_INTERMEDIATE')
    shelly_pass = config.get('INTERMEDIATE_SHELLY', 'SHELLY_PASS_INTERMEDIATE')
    if config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_TASMOTA_INTERMEDIATE'):
        return Tasmota(
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_STATUS_INTERMEDIATE'),
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_PAYLOAD_MQTT_PREFIX_INTERMEDIATE'),
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_POWER_MQTT_LABEL_INTERMEDIATE'),
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_POWER_INPUT_MQTT_LABEL_INTERMEDIATE', fallback=None),
            config.get('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_POWER_OUTPUT_MQTT_LABEL_INTERMEDIATE', fallback=None),
            config.getboolean('INTERMEDIATE_TASMOTA', 'TASMOTA_JSON_POWER_CALCULATE_INTERMEDIATE', fallback=False)
        )
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHELLY_EM_INTERMEDIATE'):
        return ShellyEM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHELLY_3EM_INTERMEDIATE'):
        return Shelly3EM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHELLY_3EM_PRO_INTERMEDIATE'):
        return Shelly3EMPro(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHELLY_1PM_INTERMEDIATE'):
        return Shelly1PM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHELLY_PLUS_1PM_INTERMEDIATE'):
        return ShellyPlus1PM(shelly_ip, shelly_user, shelly_pass)
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_SHRDZM_INTERMEDIATE'):
        return Shrdzm(
            config.get('INTERMEDIATE_SHRDZM', 'SHRDZM_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_SHRDZM', 'SHRDZM_USER_INTERMEDIATE'),
            config.get('INTERMEDIATE_SHRDZM', 'SHRDZM_PASS_INTERMEDIATE')
        )
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_EMLOG_INTERMEDIATE'):
        return Emlog(
            config.get('INTERMEDIATE_EMLOG', 'EMLOG_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_EMLOG', 'EMLOG_METERINDEX_INTERMEDIATE')
        )
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_IOBROKER_INTERMEDIATE'):
        return IoBroker(
            config.get('INTERMEDIATE_IOBROKER', 'IOBROKER_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_IOBROKER', 'IOBROKER_PORT_INTERMEDIATE'),
            config.get('INTERMEDIATE_IOBROKER', 'IOBROKER_CURRENT_POWER_ALIAS_INTERMEDIATE'),
            config.getboolean('INTERMEDIATE_IOBROKER', 'IOBROKER_POWER_CALCULATE'),
            config.get('INTERMEDIATE_IOBROKER', 'IOBROKER_POWER_INPUT_ALIAS_INTERMEDIATE'),
            config.get('INTERMEDIATE_IOBROKER', 'IOBROKER_POWER_OUTPUT_ALIAS_INTERMEDIATE')
        )
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_HOMEASSISTANT_INTERMEDIATE'):
        return HomeAssistant(
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_PORT_INTERMEDIATE'),
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_ACCESSTOKEN_INTERMEDIATE'),
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_CURRENT_POWER_ENTITY_INTERMEDIATE'),
            config.getboolean('INTERMEDIATE_HOMEASSISTANT', 'HA_POWER_CALCULATE_INTERMEDIATE'),
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_POWER_INPUT_ALIAS_INTERMEDIATE'),
            config.get('INTERMEDIATE_HOMEASSISTANT', 'HA_POWER_OUTPUT_ALIAS_INTERMEDIATE')
        )
    elif config.getboolean('SELECT_INTERMEDIATE_METER', 'USE_VZLOGGER_INTERMEDIATE'):
        return VZLogger(
            config.get('INTERMEDIATE_VZLOGGER', 'VZL_IP_INTERMEDIATE'),
            config.get('INTERMEDIATE_VZLOGGER', 'VZL_PORT_INTERMEDIATE'),
            config.get('INTERMEDIATE_VZLOGGER', 'VZL_UUID_INTERMEDIATE')
        )
    else:
        return dtu

def CreateDTU() -> DTU:
    inverter_count = config.getint('COMMON', 'INVERTER_COUNT')
    if config.getboolean('SELECT_DTU', 'USE_AHOY'):
        return AhoyDTU(
            inverter_count,
            config.get('AHOY_DTU', 'AHOY_IP')
        )
    elif config.getboolean('SELECT_DTU', 'USE_OPENDTU'):
        return OpenDTU(
            inverter_count,
            config.get('OPEN_DTU', 'OPENDTU_IP'),
            config.get('OPEN_DTU', 'OPENDTU_USER'),
            config.get('OPEN_DTU', 'OPENDTU_PASS')
        )
    else:
        raise Exception("Error: no DTU defined!")

# ----- START -----

logger.info("Author: %s / Script Version: %s",__author__, __version__)

# read config:
logger.info("read config file: " + str(Path.joinpath(Path(__file__).parent.resolve(), "HoymilesZeroExport_Config.ini")))
if args.config:
    logger.info("read additional config file: " + args.config)

VERSION = config.get('VERSION', 'VERSION')
logger.info("Config file V %s", VERSION)
DTU = CreateDTU()
POWERMETER = CreatePowermeter()
INTERMEDIATE_POWERMETER = CreateIntermediatePowermeter(DTU)
INVERTER_COUNT = config.getint('COMMON', 'INVERTER_COUNT')
LOOP_INTERVAL_IN_SECONDS = config.getint('COMMON', 'LOOP_INTERVAL_IN_SECONDS')
SET_LIMIT_DELAY_IN_SECONDS = config.getint('COMMON', 'SET_LIMIT_DELAY_IN_SECONDS')
SET_LIMIT_TIMEOUT_SECONDS = config.getint('COMMON', 'SET_LIMIT_TIMEOUT_SECONDS')
SET_LIMIT_DELAY_IN_SECONDS_MULTIPLE_INVERTER = config.getint('COMMON', 'SET_LIMIT_DELAY_IN_SECONDS_MULTIPLE_INVERTER')
SET_POWER_STATUS_DELAY_IN_SECONDS = config.getint('COMMON', 'SET_POWER_STATUS_DELAY_IN_SECONDS')
POLL_INTERVAL_IN_SECONDS = config.getint('COMMON', 'POLL_INTERVAL_IN_SECONDS')
ON_GRID_USAGE_JUMP_TO_LIMIT_PERCENT = config.getint('COMMON', 'ON_GRID_USAGE_JUMP_TO_LIMIT_PERCENT')
MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER = config.getint('COMMON', 'MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER')
SET_POWERSTATUS_CNT = config.getint('COMMON', 'SET_POWERSTATUS_CNT')
SLOW_APPROX_FACTOR_IN_PERCENT = config.getint('COMMON', 'SLOW_APPROX_FACTOR_IN_PERCENT')
LOG_TEMPERATURE = config.getboolean('COMMON', 'LOG_TEMPERATURE')
POWERMETER_TARGET_POINT = config.getint('CONTROL', 'POWERMETER_TARGET_POINT')
POWERMETER_TOLERANCE = config.getint('CONTROL', 'POWERMETER_TOLERANCE')
POWERMETER_MAX_POINT = config.getint('CONTROL', 'POWERMETER_MAX_POINT')
if POWERMETER_MAX_POINT < (POWERMETER_TARGET_POINT + POWERMETER_TOLERANCE):
    POWERMETER_MAX_POINT = POWERMETER_TARGET_POINT + POWERMETER_TOLERANCE + 50
    logger.info('Warning: POWERMETER_MAX_POINT < POWERMETER_TARGET_POINT + POWERMETER_TOLERANCE. Setting POWERMETER_MAX_POINT to ' + str(POWERMETER_MAX_POINT))
SERIAL_NUMBER = []
NAME = []
TEMPERATURE = []
HOY_MAX_WATT = []
HOY_INVERTER_WATT = []
HOY_MIN_WATT = []
CURRENT_LIMIT = []
AVAILABLE = []
LASTLIMITACKNOWLEDGED = []
HOY_BATTERY_GOOD_VOLTAGE = []
HOY_COMPENSATE_WATT_FACTOR = []
HOY_BATTERY_MODE = []
HOY_BATTERY_THRESHOLD_OFF_LIMIT_IN_V = []
HOY_BATTERY_THRESHOLD_REDUCE_LIMIT_IN_V = []
HOY_BATTERY_THRESHOLD_NORMAL_LIMIT_IN_V = []
HOY_BATTERY_NORMAL_WATT = []
HOY_BATTERY_REDUCE_WATT = []
HOY_BATTERY_THRESHOLD_ON_LIMIT_IN_V = []
HOY_BATTERY_IGNORE_PANELS = []
HOY_BATTERY_PRIORITY = []
HOY_PANEL_VOLTAGE_LIST = []
HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST = []
HOY_BATTERY_AVERAGE_CNT = []
for i in range(INVERTER_COUNT):
    SERIAL_NUMBER.append(str('yet unknown'))
    NAME.append(str('yet unknown'))
    TEMPERATURE.append(str('--- degC'))
    HOY_MAX_WATT.append(config.getint('INVERTER_' + str(i + 1), 'HOY_MAX_WATT'))
    HOY_INVERTER_WATT.append(HOY_MAX_WATT[i])
    HOY_MIN_WATT.append(int(HOY_MAX_WATT[i] * config.getint('INVERTER_' + str(i + 1), 'HOY_MIN_WATT_IN_PERCENT') / 100))
    CURRENT_LIMIT.append(int(0))
    AVAILABLE.append(bool(False))
    LASTLIMITACKNOWLEDGED.append(bool(False))
    HOY_BATTERY_GOOD_VOLTAGE.append(bool(True))
    HOY_BATTERY_MODE.append(config.getboolean('INVERTER_' + str(i + 1), 'HOY_BATTERY_MODE'))
    HOY_BATTERY_THRESHOLD_OFF_LIMIT_IN_V.append(config.getfloat('INVERTER_' + str(i + 1), 'HOY_BATTERY_THRESHOLD_OFF_LIMIT_IN_V'))
    HOY_BATTERY_THRESHOLD_REDUCE_LIMIT_IN_V.append(config.getfloat('INVERTER_' + str(i + 1), 'HOY_BATTERY_THRESHOLD_REDUCE_LIMIT_IN_V'))
    HOY_BATTERY_THRESHOLD_NORMAL_LIMIT_IN_V.append(config.getfloat('INVERTER_' + str(i + 1), 'HOY_BATTERY_THRESHOLD_NORMAL_LIMIT_IN_V'))
    HOY_BATTERY_NORMAL_WATT.append(config.getint('INVERTER_' + str(i + 1), 'HOY_BATTERY_NORMAL_WATT'))
    if HOY_BATTERY_NORMAL_WATT[i] > HOY_MAX_WATT[i]:
        HOY_BATTERY_NORMAL_WATT[i] = HOY_MAX_WATT[i]
    HOY_BATTERY_REDUCE_WATT.append(config.getint('INVERTER_' + str(i + 1), 'HOY_BATTERY_REDUCE_WATT'))
    HOY_BATTERY_THRESHOLD_ON_LIMIT_IN_V.append(config.getfloat('INVERTER_' + str(i + 1), 'HOY_BATTERY_THRESHOLD_ON_LIMIT_IN_V'))
    HOY_COMPENSATE_WATT_FACTOR.append(config.getfloat('INVERTER_' + str(i + 1), 'HOY_COMPENSATE_WATT_FACTOR'))
    HOY_BATTERY_IGNORE_PANELS.append(config.get('INVERTER_' + str(i + 1), 'HOY_BATTERY_IGNORE_PANELS'))
    HOY_BATTERY_PRIORITY.append(config.getint('INVERTER_' + str(i + 1), 'HOY_BATTERY_PRIORITY'))
    HOY_PANEL_VOLTAGE_LIST.append([])
    HOY_PANEL_MIN_VOLTAGE_HISTORY_LIST.append([])
    HOY_BATTERY_AVERAGE_CNT.append(config.getint('INVERTER_' + str(i + 1), 'HOY_BATTERY_AVERAGE_CNT'))
SLOW_APPROX_LIMIT = CastToInt(GetMaxWattFromAllInverters() * config.getint('COMMON', 'SLOW_APPROX_LIMIT_IN_PERCENT') / 100)

try:
    logger.info("---Init---")
    newLimitSetpoint = 0
    DTU.CheckVersion()
    if GetHoymilesAvailable():
        for i in range(INVERTER_COUNT):
            SetHoymilesPowerStatus(i, True)
        SetLimit(GetMinWattFromAllInverters())
        GetHoymilesActualPower()
        GetCheckBattery()
    GetPowermeterWatts()
    time.sleep(SET_LIMIT_DELAY_IN_SECONDS)
except Exception as e:
    if hasattr(e, 'message'):
        logger.error(e.message)
    else:
        logger.error(e)
    time.sleep(LOOP_INTERVAL_IN_SECONDS)
logger.info("---Start Zero Export---")

while True:
    try:
        PreviousLimitSetpoint = newLimitSetpoint
        if GetHoymilesAvailable() and GetCheckBattery():
            if LOG_TEMPERATURE:
                GetHoymilesTemperature()
            for x in range(CastToInt(LOOP_INTERVAL_IN_SECONDS / POLL_INTERVAL_IN_SECONDS)):
                powermeterWatts = GetPowermeterWatts()
                if powermeterWatts > POWERMETER_MAX_POINT:
                    if ON_GRID_USAGE_JUMP_TO_LIMIT_PERCENT > 0:
                        newLimitSetpoint = CastToInt(GetMaxInverterWattFromAllInverters() * ON_GRID_USAGE_JUMP_TO_LIMIT_PERCENT / 100)
                        if (newLimitSetpoint <= PreviousLimitSetpoint) and (ON_GRID_USAGE_JUMP_TO_LIMIT_PERCENT != 100):
                            newLimitSetpoint = PreviousLimitSetpoint + powermeterWatts - POWERMETER_TARGET_POINT
                    else:
                        newLimitSetpoint = PreviousLimitSetpoint + powermeterWatts - POWERMETER_TARGET_POINT
                    newLimitSetpoint = ApplyLimitsToSetpoint(newLimitSetpoint)
                    SetLimit(newLimitSetpoint)
                    if CastToInt(LOOP_INTERVAL_IN_SECONDS) - SET_LIMIT_DELAY_IN_SECONDS - x * POLL_INTERVAL_IN_SECONDS <= 0:
                        break
                    else:
                        time.sleep(CastToInt(LOOP_INTERVAL_IN_SECONDS) - SET_LIMIT_DELAY_IN_SECONDS - x * POLL_INTERVAL_IN_SECONDS)
                    break
                else:
                    time.sleep(POLL_INTERVAL_IN_SECONDS)

            if MAX_DIFFERENCE_BETWEEN_LIMIT_AND_OUTPUTPOWER != 100:
                CutLimit = CutLimitToProduction(newLimitSetpoint)
                if CutLimit != newLimitSetpoint:
                    newLimitSetpoint = CutLimit
                    PreviousLimitSetpoint = newLimitSetpoint

            if powermeterWatts > POWERMETER_MAX_POINT:
                continue

            # producing too much power: reduce limit
            if powermeterWatts < (POWERMETER_TARGET_POINT - POWERMETER_TOLERANCE):
                if PreviousLimitSetpoint >= GetMaxWattFromAllInverters():
                    hoymilesActualPower = GetHoymilesActualPower()
                    newLimitSetpoint = hoymilesActualPower + powermeterWatts - POWERMETER_TARGET_POINT
                    LimitDifference = abs(hoymilesActualPower - newLimitSetpoint)
                    if LimitDifference > SLOW_APPROX_LIMIT:
                        newLimitSetpoint = newLimitSetpoint + (LimitDifference * SLOW_APPROX_FACTOR_IN_PERCENT / 100)
                    if newLimitSetpoint > hoymilesActualPower:
                        newLimitSetpoint = hoymilesActualPower
                    logger.info("overproducing: reduce limit based on actual power")
                else:
                    newLimitSetpoint = PreviousLimitSetpoint + powermeterWatts - POWERMETER_TARGET_POINT
                    # check if it is necessary to approximate to the setpoint with some more passes. this reduce overshoot
                    LimitDifference = abs(PreviousLimitSetpoint - newLimitSetpoint)
                    if LimitDifference > SLOW_APPROX_LIMIT:
                        logger.info("overproducing: reduce limit based on previous limit setpoint by approximation")
                        newLimitSetpoint = newLimitSetpoint + (LimitDifference * SLOW_APPROX_FACTOR_IN_PERCENT / 100)
                    else:
                        logger.info("overproducing: reduce limit based on previous limit setpoint")

            # producing too little power: increase limit
            elif powermeterWatts > (POWERMETER_TARGET_POINT + POWERMETER_TOLERANCE):
                if PreviousLimitSetpoint < GetMaxWattFromAllInverters():
                    newLimitSetpoint = PreviousLimitSetpoint + powermeterWatts - POWERMETER_TARGET_POINT
                    logger.info("Not enough energy producing: increasing limit")
                else:
                    logger.info("Not enough energy producing: limit already at maximum")

            # check for upper and lower limits
            newLimitSetpoint = ApplyLimitsToSetpoint(newLimitSetpoint)
            # set new limit to inverter
            SetLimit(newLimitSetpoint)
        else:
            if hasattr(SetLimit, "LastLimit"):
                SetLimit.LastLimit = -1
            time.sleep(LOOP_INTERVAL_IN_SECONDS)

    except Exception as e:
        if hasattr(e, 'message'):
            logger.error(e.message)
        else:
            logger.error(e)
        time.sleep(LOOP_INTERVAL_IN_SECONDS)
