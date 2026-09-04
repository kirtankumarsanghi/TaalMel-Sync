import fs from 'fs/promises';
import path from 'path';

export interface IStorageService {
  upload(key: string, buffer: Buffer, mimeType: string): Promise<void>;
  download(key: string): Promise<Buffer>;
  delete(key: string): Promise<void>;
  exists(key: string): Promise<boolean>;
}

class LocalStorageService implements IStorageService {
  private basePath: string;

  constructor(basePath: string) {
    this.basePath = basePath;
  }

  async upload(key: string, buffer: Buffer, mimeType: string): Promise<void> {
    const fullPath = path.join(this.basePath, key);
    await fs.mkdir(path.dirname(fullPath), { recursive: true });
    await fs.writeFile(fullPath, buffer);
  }

  async download(key: string): Promise<Buffer> {
    const fullPath = path.join(this.basePath, key);
    return fs.readFile(fullPath);
  }

  async delete(key: string): Promise<void> {
    const fullPath = path.join(this.basePath, key);
    await fs.unlink(fullPath).catch(() => {}); // Ignore if already deleted
  }

  async exists(key: string): Promise<boolean> {
    const fullPath = path.join(this.basePath, key);
    try {
      await fs.access(fullPath);
      return true;
    } catch {
      return false;
    }
  }
}

class S3StorageService implements IStorageService {
  async upload(key: string, buffer: Buffer, mimeType: string): Promise<void> {
    throw new Error('S3 implementation not yet complete for Phase 2 demo');
  }

  async download(key: string): Promise<Buffer> {
    throw new Error('S3 implementation not yet complete for Phase 2 demo');
  }

  async delete(key: string): Promise<void> {
    throw new Error('S3 implementation not yet complete for Phase 2 demo');
  }

  async exists(key: string): Promise<boolean> {
    throw new Error('S3 implementation not yet complete for Phase 2 demo');
  }
}

export function getStorageService(): IStorageService {
  const provider = process.env.STORAGE_PROVIDER || 'local';
  if (provider === 'local') {
    const localPath = process.env.STORAGE_LOCAL_PATH || './data/uploads';
    return new LocalStorageService(localPath);
  } else if (provider === 's3') {
    return new S3StorageService();
  }
  throw new Error(`Unknown storage provider: ${provider}`);
}
