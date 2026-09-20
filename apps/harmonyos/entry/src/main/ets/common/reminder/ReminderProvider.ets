export interface ReminderRequest {
  title: string;
  content: string;
  triggerAt: string;
}

export interface ReminderProvider {
  schedule(request: ReminderRequest): Promise<string>;
  cancel(reminderId: string): Promise<void>;
}

/** Development-only adapter until the official agent-reminder capability is approved. */
export class MockReminderProvider implements ReminderProvider {
  private nextId: number = 1;

  async schedule(request: ReminderRequest): Promise<string> {
    void request;
    const id = `mock-reminder-${this.nextId}`;
    this.nextId += 1;
    return id;
  }

  async cancel(reminderId: string): Promise<void> {
    void reminderId;
  }
}

export class UnavailableReminderProvider implements ReminderProvider {
  async schedule(request: ReminderRequest): Promise<string> {
    void request;
    throw new Error('主动提醒功能尚未开放');
  }

  async cancel(reminderId: string): Promise<void> {
    void reminderId;
    throw new Error('主动提醒功能尚未开放');
  }
}
