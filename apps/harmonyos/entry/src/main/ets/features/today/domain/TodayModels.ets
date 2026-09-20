export interface TodayActiveThing {
  thing_id: string;
  name: string;
  current_stage?: string;
  open_task_count: number;
}

export interface TodaySnapshot {
  active: TodayActiveThing[];
  upcoming: TodayUpcomingThing[];
  overdue: TodayUpcomingThing[];
  due_today: TodayUpcomingThing[];
  blocked: TodayBlockedThing[];
  recent: TodayRecentThing[];
  attention: Object[];
  generated_at: string;
}
export interface TodayUpcomingThing {
  thing_id: string;
  name: string;
  deadline_at: string;
  open_task_count: number;
}

export interface TodayBlockedThing {
  thing_id: string;
  thing_name: string;
  description: string;
  severity: string;
}

export interface TodayRecentThing {
  thing_id: string;
  name: string;
  status: string;
  updated_at: string;
}
