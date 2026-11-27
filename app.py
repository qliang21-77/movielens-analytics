import re
import time
import pandas as pd
import streamlit as st
import mysql.connector
import altair as alt

st.set_page_config(page_title='MovieLens Analytics', layout='wide')
st.title('MovieLens Analytics')
st.caption('DSCI 551 | Movie Rating and Database Performance Analysis')
with st.sidebar:
    page = st.radio('Navigation', ['Database','Data Overview','Query Workload','Performance Experiments'])
    st.caption('Cloud database · MovieLens')

try:
    config = st.secrets['mysql']
    host = config['host']
    user = config['user']
    password = config['password']
    database = config['database']
    port = int(config.get('port', 3306))
except (KeyError, FileNotFoundError):
    st.error('Database configuration is missing. Please contact the app administrator.')
    st.stop()

def run(sql, params=(), schema=None):
    with mysql.connector.connect(host=host, port=port, user=user, password=password,
                                 database=schema or database, connection_timeout=20,
                                 ssl_disabled=False, ssl_verify_cert=True,
                                 ssl_verify_identity=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return pd.DataFrame(cur.fetchall(), columns=cur.column_names)

def show(sql, params=(), chart=None):
    with st.expander('View SQL'):
        st.code(sql, language='sql')
        st.write('Parameters:', params)
    df=run(sql,params)
    for c in df.columns:
        if c not in ['title','genreName','activity_range','release_year_range','table_name']:
            try:
                df[c]=pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    st.dataframe(df, hide_index=True, use_container_width=True)
    if chart and not df.empty:
        kind,x,y=chart
        getattr(st,kind+'_chart')(df,x=x,y=y)
    return df

TOP='''SELECT m.movieId, m.title, COUNT(r.rating) AS rating_count,
ROUND(AVG(r.rating),2) AS average_rating
FROM movies m JOIN ratings r ON m.movieId=r.movieId
GROUP BY m.movieId,m.title HAVING COUNT(r.rating)>=%s
ORDER BY average_rating DESC,rating_count DESC'''
CTE='''WITH top_movies AS (
SELECT movieId,COUNT(rating) AS rating_count,ROUND(AVG(rating),2) AS average_rating
FROM ratings GROUP BY movieId HAVING COUNT(rating)>=%s
ORDER BY average_rating DESC,rating_count DESC LIMIT %s)
SELECT tm.movieId,m.title,tm.rating_count,tm.average_rating
FROM top_movies tm JOIN movies m ON tm.movieId=m.movieId
ORDER BY tm.average_rating DESC,tm.rating_count DESC'''
GENRE='''SELECT g.genreId,g.genreName,COUNT(DISTINCT mg.movieId) AS num_movies,
COUNT(r.rating) AS num_ratings,ROUND(AVG(r.rating),2) AS avg_rating
FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId
LEFT JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName
ORDER BY num_movies DESC'''
ACTIVITY='''WITH user_activity AS (SELECT u.userId,COUNT(DISTINCT r.movieId) AS num_movies_rated
FROM users u LEFT JOIN ratings r ON u.userId=r.userId GROUP BY u.userId)
SELECT CASE WHEN num_movies_rated<50 THEN '0-49' WHEN num_movies_rated<100 THEN '50-99'
WHEN num_movies_rated<200 THEN '100-199' WHEN num_movies_rated<500 THEN '200-499'
WHEN num_movies_rated<1000 THEN '500-999' ELSE '1000+' END AS activity_range,
COUNT(*) AS num_users FROM user_activity GROUP BY activity_range ORDER BY MIN(num_movies_rated)'''
NORMAL='''WITH movie_stats AS (SELECT m.movieId,COUNT(r.rating) AS rating_count,
SUM(r.rating) AS total_rating_score,AVG(r.rating) AS movie_avg_rating
FROM movies m LEFT JOIN ratings r ON m.movieId=r.movieId GROUP BY m.movieId)
SELECT g.genreName,COUNT(ms.movieId) AS movie_count,SUM(ms.rating_count) AS total_ratings,
ROUND(AVG(ms.rating_count),2) AS avg_ratings_received_per_movie,
ROUND(SUM(ms.total_rating_score)/NULLIF(SUM(ms.rating_count),0),2) AS weighted_avg_rating,
ROUND(AVG(ms.movie_avg_rating),2) AS movie_level_avg_rating
FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN movie_stats ms ON mg.movieId=ms.movieId
GROUP BY g.genreId,g.genreName ORDER BY total_ratings DESC'''
FAVORITE='''WITH user_genre_ratings AS (SELECT r.userId,g.genreName,COUNT(*) AS favorite_count
FROM ratings r JOIN movie_genres mg ON r.movieId=mg.movieId JOIN genres g ON mg.genreId=g.genreId
WHERE r.rating >= %s GROUP BY r.userId,g.genreId,g.genreName),
ranked_genres AS (SELECT userId,genreName,favorite_count,RANK() OVER(PARTITION BY userId ORDER BY favorite_count DESC) AS genre_rank FROM user_genre_ratings)
SELECT userId,genreName,favorite_count FROM ranked_genres WHERE genre_rank=1'''

def overview():
    st.header('Data Overview')
    tables=['movies','users','ratings','genres','tags','links','movie_genres']
    df=run('SELECT '+','.join(f'(SELECT COUNT(*) FROM {t}) AS {t}' for t in tables))
    for cols, names in [(st.columns(4),tables[:4]),(st.columns(3),tables[4:])]:
        for col,t in zip(cols,names): col.metric(t.replace('_',' ').title(),f'{df.iloc[0][t]:,}')
    st.subheader('Estimated Database Size (MB)')
    show('''SELECT ROUND(SUM(data_length)/1048576,2) AS data_MB,
ROUND(SUM(index_length)/1048576,2) AS index_MB,
ROUND(SUM(data_length+index_length)/1048576,2) AS total_MB
FROM information_schema.tables WHERE table_schema=DATABASE()''')
    st.subheader('Rating Summary')
    show('SELECT COUNT(*) AS total_ratings,MIN(rating) AS min_rating,MAX(rating) AS max_rating,ROUND(AVG(rating),2) AS avg_rating,ROUND(STDDEV_POP(rating),2) AS std_rating FROM ratings')
    st.subheader('Movie Distribution by Genre')
    df=show(GENRE)
    for y in ['num_movies','num_ratings','avg_rating']: st.bar_chart(df,x='genreName',y=y,horizontal=True)
    st.caption('Movies and ratings can contribute to multiple genres.')
    st.subheader('User Rating Activity')
    df = show(ACTIVITY)
    activity_order = [
        '0-49',
        '50-99',
        '100-199',
        '200-499',
        '500-999',
        '1000+'
    ]

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X(
            'activity_range:N',
            sort=activity_order,
            title='Number of Movies Rated',
            axis=alt.Axis(labelAngle=0)
        ),
        y=alt.Y(
            'num_users:Q',
            title='Number of Users',
            scale=alt.Scale(zero=True)
        ),
        tooltip=['activity_range', 'num_users']
    ).properties(
        height=350
    )

    st.altair_chart(chart, use_container_width=True)

def database_page():
    st.header('Database')
    st.caption('Implemented schema, loading pipeline, relationships and live representative data.')
    tables = ['movies', 'users', 'ratings', 'genres', 'tags', 'links', 'movie_genres']
    a,b,c,d = st.tabs(['Schema Design', 'Load Dataset', 'Representative Data', 'Database Size'])
    with a:
        st.subheader('Relational Schema and Entity Relationships')
        st.markdown("""| Entity / Table | Related Table | Relationship | Description |
|---|---|---|---|
| users | ratings | One-to-many | One user can rate multiple movies, while each rating belongs to one user |
| users | tags | One-to-many | One user can create multiple tags, while each tag record belongs to one user |
| users | movies | Many-to-many | One user can rate multiple movies One movie can have ratings from multiple users One user can only rate one movie at most once. The ratings table connects the two entities, where each user could at most once rate a particular movie |
| movies | ratings | One-to-many | One movie can receive multiple ratings, while each rating belongs to one movie|
| movies | tags | One-to-many | One movie can have multiple tags, while each tag record belongs to one movie|
| movies | links | One-to-one | One movie only has one link, and each link record belongs to one movie|
| movies | genres | Many-to-many (via movie_genres) | One movie can belong to multiple genres, and one genre can be associated with multiple movies. The movie_genres junction table connects the two tables through movieId and genreId|
| movies | movie_genres | One-to-many | One movie can belong to many movie genres, and each record references one movie |
| genres | movie_genres | One-to-many | One genre can be associated with multiple movies through the movie_genres table, while each movie-genre record references one genre|
""")
        st.caption( 'The ratings and tags tables represent many-to-many '
    'relationships between users and movies, while '
    'movie_genres resolves the many-to-many relationship '
    'between movies and genres.')
        table = st.selectbox('Inspect table structure', tables)
        ddl = run(f'SHOW CREATE TABLE `{table}`')
        st.code(str(ddl.iloc[0,1]), language='sql')
        st.subheader('Live Key Constraints')
        show("""SELECT table_name, constraint_name, column_name,
        referenced_table_name, referenced_column_name
        FROM information_schema.key_column_usage
        WHERE table_schema=DATABASE()
        ORDER BY table_name,constraint_name,ordinal_position""")
    with b:
        st.subheader('Create Database and Load Dataset')
        st.caption('Reproduction examples for local MySQL. These statements are displayed only, never executed by this app. The deployed schema is configured separately.')
        st.code('CREATE DATABASE IF NOT EXISTS project_551;\nUSE project_551;', language='sql')
        st.markdown('**1. Import the four original MovieLens CSV files**')
        fields = {'movies':'movieId, title, genres', 'ratings':'userId, movieId, rating, timestamp', 'tags':'userId, movieId, tag, timestamp', 'links':'movieId, imdbId, tmdbId'}
        st.caption('Create the tables first using the schema shown in Schema Design. For a fresh load, stage ratings and tags or populate users before importing dependent rows so foreign keys remain valid.')
        for name, columns in fields.items():
            with st.expander(name + '.csv'):
                st.code(f"""LOAD DATA LOCAL INFILE 'PATH_TO_ML_LATEST_SMALL/{name}.csv'
INTO TABLE {name}
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '"'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
({columns});""", language='sql')
        st.markdown('**2. Derive unique users from ratings and tags**')
        st.caption('For a fresh import with foreign keys enabled, use staging tables as the source of this UNION before loading ratings and tags. The following illustrates the transformation in the project documentation.')
        st.code('INSERT INTO users (userId)\nSELECT userId FROM ratings\nUNION\nSELECT userId FROM tags;', language='sql')
        st.markdown('**3. Normalize movie genres**')
        st.write('Split pipe-separated genre names, remove duplicates, exclude (no genres listed), and populate the movie-to-genre bridge table.')
        split = """SELECT m.movieId, TRIM(REPLACE(SUBSTRING_INDEX(
    SUBSTRING_INDEX(m.genres, '|', n.n), '|', -1), CHAR(13), '')) AS genre
FROM movies m JOIN (
    SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
    UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
    UNION SELECT 9 UNION SELECT 10
) n ON CHAR_LENGTH(m.genres)-CHAR_LENGTH(REPLACE(m.genres,'|','')) >= n.n-1"""
        st.code('INSERT INTO genres (genreName)\nSELECT DISTINCT genre FROM (\n'+split+"\n) x WHERE genre <> '(no genres listed)';", language='sql')
        st.code('INSERT INTO movie_genres (movieId, genreId)\nSELECT DISTINCT x.movieId, g.genreId FROM (\n'+split+'\n) x JOIN genres g ON x.genre=g.genreName;', language='sql')
        st.markdown('**4. Cloud deployment**')
        st.write('Export local MySQL structure and data, import the SQL dump into cloud MySQL, and connect Streamlit using server-side secrets.')
    with c:
        st.subheader('Live Representative Data')
        sample = st.selectbox('Select a table', tables)
        limit = st.slider('Sample rows', 5, 50, 10, key='db_sample_limit')
        sql = f'SELECT * FROM `{sample}` LIMIT %s'
        st.code(sql, language='sql')
        st.dataframe(run(sql,(limit,)), hide_index=True, use_container_width=True)
        st.caption('Representative sample, not a random or ordered sample.')
    with d:
        st.subheader('Live Row Counts')
        show(' UNION ALL '.join(f"SELECT '{t}' AS table_name, COUNT(*) AS row_count FROM `{t}`" for t in tables))
        st.subheader('Estimated Storage by Table (MB)')
        show("""SELECT table_name, ROUND(data_length/1048576,2) AS data_MB,
        ROUND(index_length/1048576,2) AS index_MB,
        ROUND((data_length+index_length)/1048576,2) AS total_MB
        FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_type='BASE TABLE' ORDER BY total_MB DESC""")
        st.subheader('Total Estimated Database Size (MB)')
        show("""SELECT ROUND(SUM(data_length)/1048576,2) AS data_MB,
        ROUND(SUM(index_length)/1048576,2) AS index_MB,
        ROUND(SUM(data_length+index_length)/1048576,2) AS total_MB
        FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_type='BASE TABLE'""")
        st.caption('InnoDB storage estimates include allocated data and index pages; exact row counts are queried separately.')

def queries():
    st.header('Query Workload')
    q=st.selectbox('Research Question',['Q1 — Top Rated Movies','Q2 — Average Rating by Genre','Q3 — Genre Popularity vs. Rating','Q4 — Genre and User Engagement','Q5 — Release Period vs. Rating','Q6 — Favorite Genre by User'])
    chart=None; params=()
    if q.startswith('Q1'):
        minimum=st.number_input('Minimum ratings',1,100000,50); n=st.slider('Top N',1,100,10)
        sql=TOP+' LIMIT %s'; params=(minimum,n)
    elif q.startswith('Q2'):
        minimum=st.number_input('Minimum ratings per genre',1,100000,50)
        sql='''SELECT g.genreName,COUNT(r.rating) AS rating_count,ROUND(AVG(r.rating),2) AS average_rating FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName HAVING COUNT(r.rating)>=%s ORDER BY average_rating DESC,rating_count DESC'''; params=(minimum,); chart=('bar','genreName','average_rating')
    elif q.startswith('Q3'):
        mode=st.radio('Popularity measure',['Before normalization','After normalization'])
        if mode=='Before normalization':
            sql='''SELECT g.genreName,COUNT(DISTINCT mg.movieId) AS movie_count,COUNT(r.rating) AS rating_count,ROUND(AVG(r.rating),2) AS average_rating FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName ORDER BY rating_count DESC'''; chart=('scatter','rating_count','average_rating')
        else:
            sql=NORMAL; chart=('scatter','avg_ratings_received_per_movie','movie_level_avg_rating')
    elif q.startswith('Q4'):
        genres=run('SELECT genreName FROM genres ORDER BY genreName')['genreName'].tolist()
        genre=st.selectbox('Genre',['All genres']+genres)
        sql='''SELECT g.genreName,COUNT(r.rating) AS rating_count,COUNT(DISTINCT r.userId) AS unique_users,ROUND(COUNT(DISTINCT r.userId)*100.0/(SELECT COUNT(*) FROM users),2) AS user_participation_pct FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId'''
        if genre!='All genres': sql+=' WHERE g.genreName=%s'; params=(genre,)
        sql+=' GROUP BY g.genreId,g.genreName ORDER BY rating_count DESC'; chart=('bar','genreName','user_participation_pct')
    elif q.startswith('Q5'):
        lo,hi=st.slider('Release decades',1900,2020,(1900,2010),10)
        sql='''WITH movie_stats AS (SELECT m.movieId,FLOOR(CAST(SUBSTRING(m.title,-5,4) AS UNSIGNED)/10)*10 AS decade,COUNT(r.rating) AS rating_count,AVG(r.rating) AS movie_avg_rating FROM movies m JOIN ratings r ON m.movieId=r.movieId WHERE m.title REGEXP '[(][0-9]{4}[)]$' GROUP BY m.movieId,m.title) SELECT CONCAT(decade,'-',decade+9) AS release_year_range,COUNT(*) AS movie_count,SUM(rating_count) AS total_ratings,ROUND(AVG(movie_avg_rating),2) AS movie_level_avg_rating FROM movie_stats WHERE decade BETWEEN %s AND %s GROUP BY decade ORDER BY decade'''; params=(lo,hi); chart=('line','release_year_range','movie_level_avg_rating')
    else:
        threshold=st.slider('Minimum rating to count as a favorite',0.5,5.0,4.0,0.5)
        users=run('SELECT userId FROM users ORDER BY userId')['userId'].tolist()
        uid=st.selectbox('User',['All users']+users)
        sql=FAVORITE; params=(threshold,)
        if uid!='All users': sql+=' AND userId=%s'; params+=(uid,)
        sql+=' ORDER BY favorite_count DESC,userId,genreName'
        if uid=='All users': sql+=' LIMIT 10'
        st.caption('Ties are retained by RANK; the all-users view displays the top 10 rows.')
    if st.button('Run Query',type='primary'):
        show(sql,params,chart)

def experiments():
    st.header('Performance Experiments')
    st.caption('Historical measurements from the report; single runs, not live benchmarks.')
    a,b,c=st.tabs(['Indexing','Sorting and Join','Live Query Lab'])
    with a:
        df=pd.DataFrame({'Index configuration':['movieId','movieId, rating','rating, movieId'],'Execution time (ms)':[214,112,195]})
        st.dataframe(df,hide_index=True); st.bar_chart(df,x='Index configuration',y='Execution time (ms)'); st.metric('Observed reduction', '47.66%')
        st.caption('The composite index was used as a covering lookup; the reversed index was not selected in the recorded plan.')
    with b:
        df=pd.DataFrame({'Strategy':['Full sort','Top-N','Early aggregation CTE'],'Execution time (ms)':[193,191,96.9],'Join output':[100836,100836,10],'Main sort record bytes':[1080,1080,37],'Main sort peak bytes':[85712,85712,36560],'Disk spills':[0,0,0]})
        st.dataframe(df,hide_index=True); st.bar_chart(df,x='Strategy',y='Execution time (ms)'); st.metric('Observed reduction vs Top-N','49.27%')
    with c:
        schema=database
        st.caption('Live experiments use the cloud database and its current indexes. Timings are not directly comparable with historical local measurements.')
        strategy=st.radio('Query strategy',['Full sorting','Top-N','Early aggregation CTE'])
        minimum=st.number_input('Minimum rating count',1,100000,50,key='lab_min'); n=st.slider('Top N',1,100,10,key='lab_n')
        sql=CTE if strategy=='Early aggregation CTE' else TOP+(' LIMIT %s' if strategy=='Top-N' else '')
        params=(minimum,) if strategy=='Full sorting' else (minimum,n)
        st.code('EXPLAIN ANALYZE\n'+sql,language='sql')
        if st.button('Run live experiment'):
            st.subheader('Current ratings indexes')
            st.dataframe(run('SHOW INDEX FROM ratings',schema=schema),hide_index=True)
            start=time.perf_counter(); df=run('EXPLAIN ANALYZE '+sql,params,schema); elapsed=(time.perf_counter()-start)*1000
            plan='\n'.join(str(x) for x in df.iloc[:,0]); st.code(plan,language='text')
            match=re.search(r'actual time=[\d.]+\.\.([\d.]+)',plan)
            if match: st.metric('Root iterator completion time',match.group(1)+' ms')
            st.caption(f'Client elapsed time including connection and retrieval: {elapsed:.1f} ms. No indexes are created or dropped by this app.')
try:
    if page=='Data Overview': overview()
    elif page=='Database': database_page()
    elif page=='Query Workload': queries()
    else: experiments()
except mysql.connector.Error as e:
    st.error('Database query failed. Please try again or contact the app administrator.')
