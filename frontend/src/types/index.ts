export type TaskStatus = 'pending' | 'downloading' | 'paused' | 'processing' | 'completed' | 'failed';
export type ContentType = 'video' | 'image_set' | 'long_video';
export type CookieStatus = 'valid' | 'invalid' | 'untested';

export interface TaskItem {
  id: number;
  taskId: number;
  awemeId: string;
  title: string;
  author: string;
  type: ContentType;
  duration: string;
  imageCount: number;
  coverUrl: string;
  status: TaskStatus;
  progress: number; // 0-100
  downloadedBytes: number;
  totalBytes: number;
  failReason?: string;
  localPath?: string;
  createdAt: string;
}

export interface ParsedURL {
  url: string;
  type: ContentType | 'user_home';
  awemeId?: string;
  secUserId?: string;
  title?: string;
  author?: string;
  coverUrl?: string;
  duration?: string;
  imageCount?: number;
}

export interface CookieItem {
  id: number;
  label: string;
  status: CookieStatus;
  lastUsed: string;
  lastCheck: string;
  failCount: number;
}

export interface AppConfig {
  downloadDir: string;
  concurrency: number;
  chunkSize: number;
  metadataFormats: ('json' | 'csv')[];
  titleTruncate: number;
}

export interface NavItem {
  id: string;
  path: string;
  label: string;
  icon: string;
}

export interface DownloadStats {
  total: number;
  downloading: number;
  completed: number;
  failed: number;
}