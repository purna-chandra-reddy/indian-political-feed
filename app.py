import os
import json
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import feedparser
import re
from urllib.parse import urlparse
import hashlib

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
DATA_FILE = 'posts.json'
USERS_FILE = 'users.json'

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def load_posts():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_posts(posts):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

def fetch_enhanced_news():
    """Fetch news from multiple Indian sources including memes and trending topics"""
    feeds = {
        'andhra_pradesh': [
            'https://timesofindia.indiatimes.com/rssfeeds/-2128816011.cms',
            'https://www.thehindu.com/news/national/andhra-pradesh/feeder/default.rss'
        ],
        'telangana': [
            'https://timesofindia.indiatimes.com/rssfeeds/-2128816011.cms',
            'https://www.thehindu.com/news/national/telangana/feeder/default.rss'
        ],
        'india_politics': [
            'https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms',
            'https://www.thehindu.com/news/national/feeder/default.rss',
            'https://indianexpress.com/section/india/feed/'
        ],
        'trending': [
            'https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms',  # Entertainment
            'https://www.thehindu.com/sport/feeder/default.rss'  # Sports
        ]
    }
    
    news = {}
    for region, urls in feeds.items():
        news[region] = []
        for url in urls:
            try:
                parsed = feedparser.parse(url)
                for entry in parsed.entries[:3]:  # Limit to avoid overwhelming
                    news[region].append({
                        'title': entry.title,
                        'link': entry.link,
                        'summary': getattr(entry, 'summary', '')[:200] + '...' if hasattr(entry, 'summary') else '',
                        'published': getattr(entry, 'published', ''),
                        'source': urlparse(url).netloc
                    })
            except Exception as e:
                print(f"Error fetching from {url}: {e}")
                continue
    
    return news

def get_trending_hashtags(posts):
    """Extract trending hashtags from posts"""
    hashtag_count = {}
    for post in posts:
        hashtags = re.findall(r'#\w+', post.get('text', '').lower())
        for tag in hashtags:
            hashtag_count[tag] = hashtag_count.get(tag, 0) + 1
    
    # Return top 10 trending hashtags
    return sorted(hashtag_count.items(), key=lambda x: x[1], reverse=True)[:10]

def detect_meme_content(text):
    """Simple meme detection based on keywords and patterns"""
    meme_keywords = ['lol', 'meme', 'funny', 'joke', '😂', '🤣', 'haha', 'savage', 'rofl']
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in meme_keywords)

def get_post_engagement_score(post):
    """Calculate engagement score for better sorting"""
    likes = post.get('likes', 0)
    comments = len(post.get('comments', []))
    shares = post.get('shares', 0)
    
    # Time decay factor (newer posts get slight boost)
    try:
        time_diff = datetime.utcnow() - datetime.fromisoformat(post['timestamp'])
        time_factor = max(0.1, 1 - (time_diff.days / 7))  # Decay over a week
    except (KeyError, ValueError):
        time_factor = 0.1  # Default for posts without valid timestamp
    
    return (likes * 2 + comments * 3 + shares * 5) * time_factor

@app.route('/', methods=['GET'])
def index():
    sort = request.args.get('sort', 'latest')
    filter_type = request.args.get('filter', 'all')
    posts = load_posts()
    
    # Filter posts
    if filter_type == 'memes':
        posts = [p for p in posts if detect_meme_content(p.get('text', ''))]
    elif filter_type == 'political':
        political_keywords = ['politics', 'government', 'minister', 'party', 'election', 'vote']
        posts = [p for p in posts if any(keyword in p.get('text', '').lower() for keyword in political_keywords)]
    
    # Sort posts
    if sort == 'popular':
        posts.sort(key=get_post_engagement_score, reverse=True)
    elif sort == 'trending':
        def trending_score(post):
            try:
                time_diff = datetime.utcnow() - datetime.fromisoformat(post['timestamp'])
                time_factor = 1 if time_diff.total_seconds() < 86400 else 0.5  # 24 hours
                return (post.get('likes', 0) + len(post.get('comments', []))) * time_factor
            except (KeyError, ValueError):
                return 0
        posts.sort(key=trending_score, reverse=True)
    else:  # latest
        posts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    news = fetch_enhanced_news()
    trending_hashtags = get_trending_hashtags(posts)
    
    return render_template('index.html', 
                         posts=posts, 
                         news=news, 
                         trending_hashtags=trending_hashtags,
                         current_sort=sort,
                         current_filter=filter_type)

@app.route('/post', methods=['POST'])
def post():
    text = request.form.get('text', '').strip()
    username = request.form.get('username', 'Anonymous').strip()
    file = request.files.get('photo')
    
    if not text and not file:
        return redirect(url_for('index'))
    
    filename = None
    if file and file.filename:
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov'}
        if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
            filename = secure_filename(f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    
    posts = load_posts()
    
    # Auto-detect content type
    is_meme = detect_meme_content(text)
    
    new_post = {
        'id': hashlib.md5(f"{username}{text}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:8],
        'username': username,
        'text': text,
        'photo': filename,
        'timestamp': datetime.utcnow().isoformat(),
        'likes': 0,
        'shares': 0,
        'comments': [],
        'is_meme': is_meme,
        'hashtags': re.findall(r'#\w+', text.lower())
    }
    
    posts.append(new_post)
    save_posts(posts)
    return redirect(url_for('index'))

@app.route('/like/<post_id>', methods=['POST'])
def like(post_id):
    posts = load_posts()
    for post in posts:
        if post.get('id') == post_id:
            post['likes'] = post.get('likes', 0) + 1
            break
    save_posts(posts)
    return redirect(url_for('index'))

@app.route('/share/<post_id>', methods=['POST'])
def share(post_id):
    posts = load_posts()
    for post in posts:
        if post.get('id') == post_id:
            post['shares'] = post.get('shares', 0) + 1
            break
    save_posts(posts)
    return jsonify({'success': True})

@app.route('/comment/<post_id>', methods=['POST'])
def comment(post_id):
    comment_text = request.form.get('comment', '').strip()
    username = request.form.get('username', 'Anonymous').strip()
    
    if not comment_text:
        return redirect(url_for('index'))
    
    posts = load_posts()
    for post in posts:
        if post.get('id') == post_id:
            if 'comments' not in post:
                post['comments'] = []
            # Ensure comment is a dictionary with all required fields
            new_comment = {
                'username': username,
                'text': comment_text,
                'timestamp': datetime.utcnow().isoformat()
            }
            post['comments'].append(new_comment)
            break
    
    save_posts(posts)
    return redirect(url_for('index'))

@app.route('/api/posts')
def api_posts():
    """API endpoint for dynamic loading"""
    posts = load_posts()
    return jsonify(posts)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip().lower()
    posts = load_posts()
    
    if query:
        filtered_posts = []
        for post in posts:
            if (query in post.get('text', '').lower() or 
                query in post.get('username', '').lower() or
                any(query in hashtag for hashtag in post.get('hashtags', []))):
                filtered_posts.append(post)
        posts = filtered_posts
    
    return render_template('search_results.html', posts=posts, query=query)

# Add this custom filter for safe template access
@app.template_filter('safe_get')
def safe_get(dictionary, key, default=''):
    """Safe dictionary access for templates"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, default)
    return default

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)