# clutch-connector-rss

RSS and Atom feed connector for [Clutch](https://github.com/malay-kumar/clutch).

## Install

```bash
pip install clutch-connector-rss
```

## Config

```yaml
# clutch.yaml
connectors:
  rss:
    enabled: true
    feeds:
      - https://dev.to/feed
      - https://news.ycombinator.com/rss
      - https://your-favorite-blog.com/rss
```

## What It Fetches

- Reads RSS 2.0 and Atom feeds
- Extracts: title, summary, published date, author, link
- Caps at 20 entries per feed per run
- No authentication needed for public feeds

## License

MIT
