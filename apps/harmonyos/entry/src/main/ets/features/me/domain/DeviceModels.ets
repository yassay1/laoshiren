export interface Device {
  device_id: string;
  platform: string;
  timezone: string;
  active: boolean;
  last_seen_at: string;
}

export interface RegisterDeviceBody {
  device_id: string;
  timezone: string;
  platform: string;
}

export interface PushTokenBody {
  push_token: string;
  provider: string;
}
